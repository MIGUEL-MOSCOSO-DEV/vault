import os
import secrets
import shutil
import struct
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .database import connection

MAGIC = b"VAULT1"
CHUNK = 1024 * 1024


def derive(password, salt):
    if len(password) < 12:
        raise ValueError("La contraseña necesita al menos 12 caracteres.")
    return Scrypt(salt=salt, length=32, n=32768, r=8, p=1).derive(password.encode())


def encrypt(source, destination, password):
    salt, prefix = secrets.token_bytes(16), secrets.token_bytes(8)
    header = MAGIC + salt + prefix
    cipher = AESGCM(derive(password, salt))
    with open(source, "rb") as incoming, open(destination, "xb") as outgoing:
        outgoing.write(header)
        counter = 0
        while True:
            data = incoming.read(CHUNK)
            number = struct.pack(">I", counter)
            sealed = cipher.encrypt(prefix + number, data, header + number)
            outgoing.write(struct.pack(">I", len(sealed)))
            outgoing.write(sealed)
            counter += 1
            if not data:
                break


def decrypt(source, destination, password):
    with open(source, "rb") as incoming, open(destination, "xb") as outgoing:
        header = incoming.read(30)
        if len(header) != 30 or header[:6] != MAGIC:
            raise ValueError("No es un respaldo Vault compatible.")
        cipher = AESGCM(derive(password, header[6:22]))
        counter = 0
        while True:
            size = incoming.read(4)
            if len(size) != 4:
                raise ValueError("Respaldo incompleto.")
            length = struct.unpack(">I", size)[0]
            if not 16 <= length <= CHUNK + 16:
                raise ValueError("Bloque de respaldo inválido.")
            sealed = incoming.read(length)
            if len(sealed) != length:
                raise ValueError("Respaldo incompleto.")
            number = struct.pack(">I", counter)
            data = cipher.decrypt(header[22:30] + number, sealed, header + number)
            if not data:
                if incoming.read(1):
                    raise ValueError("Hay datos inesperados tras el respaldo.")
                return
            outgoing.write(data)
            counter += 1


def walk_files(source):
    for folder, directories, files in os.walk(source, followlinks=False):
        directories[:] = [
            name
            for name in directories
            if not (getattr((Path(folder) / name).lstat(), "st_file_attributes", 0) & 0x400)
            and not (Path(folder) / name).is_symlink()
        ]
        for name in directories + files:
            path = Path(folder) / name
            if not (getattr(path.lstat(), "st_file_attributes", 0) & 0x400):
                yield path


def snapshot(source, destination, password):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_dir():
        raise ValueError("Selecciona una carpeta de origen existente.")
    if destination == source or source in destination.parents:
        raise ValueError("El destino debe estar fuera de la carpeta respaldada.")
    destination.mkdir(parents=True, exist_ok=True)
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    final = destination / (name + ".vault")
    partial = destination / (name + ".partial")
    files, total = 0, 0
    try:
        with tempfile.TemporaryDirectory(prefix="vault-") as temporary:
            archive = Path(temporary) / "archive.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                for path in walk_files(source):
                    if path.is_symlink():
                        continue
                    if path.is_file():
                        resolved = path.resolve()
                        if source not in resolved.parents:
                            continue
                        bundle.write(path, path.relative_to(source).as_posix())
                        files += 1
                        total += path.stat().st_size
                    elif path.is_dir():
                        bundle.write(path, path.relative_to(source).as_posix() + "/")
            encrypt(archive, partial, password)
        os.replace(partial, final)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return {
        "path": str(final),
        "files": files,
        "bytes": total,
        "created": datetime.now(timezone.utc).isoformat(),
    }


def restore(archive, destination, password):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("La carpeta de restauración debe ser nueva; no se sobrescriben archivos.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vault-restore-", dir=destination.parent) as temporary:
        temporary = Path(temporary)
        plain = temporary / "archive.zip"
        decrypt(archive, plain, password)
        staging = temporary / "contents"
        staging.mkdir()
        with zipfile.ZipFile(plain) as bundle:
            members = bundle.infolist()
            if len(members) > 100000 or sum(item.file_size for item in members) > 50 * 1024**3:
                raise ValueError(
                    "El respaldo excede el límite de restauración de 50 GB o 100000 entradas."
                )
            for member in members:
                path = PurePosixPath(member.filename)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or ":" in member.filename
                    or "\\" in member.filename
                ):
                    raise ValueError("El respaldo contiene una ruta no segura.")
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("No se restauran enlaces simbólicos.")
                target = staging.joinpath(*path.parts).resolve()
                if target != staging and staging not in target.parents:
                    raise ValueError("Ruta fuera del destino.")
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(member) as incoming, target.open("xb") as outgoing:
                        shutil.copyfileobj(incoming, outgoing, CHUNK)
        os.replace(staging, destination)
    return destination


class History:
    def __init__(self, path):
        self.path = path
        with connection(path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY, created TEXT, path TEXT, files INTEGER, bytes INTEGER)"
            )

    def add(self, result):
        with connection(self.path) as db:
            db.execute(
                "INSERT INTO snapshots(created,path,files,bytes) VALUES(?,?,?,?)",
                (result["created"], result["path"], result["files"], result["bytes"]),
            )

    def all(self):
        with connection(self.path) as db:
            return db.execute(
                "SELECT created,path,files,bytes FROM snapshots ORDER BY id DESC"
            ).fetchall()
