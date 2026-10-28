import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .backup import History, restore, snapshot
from .paths import data_dir
from .ui import Tasks, field, table, theme


class Vault:
    def __init__(self, root):
        self.root = root
        self.busy = False
        self.next_run = None
        self.root.title("Vault — Respaldos privados")
        self.root.geometry("1040x840")
        theme(root, "#f3f1e9", "#243930", "#a5c9aa")
        self.tasks = Tasks(root)
        self.history = History(data_dir() / "history.sqlite")
        hero = ttk.Frame(root, padding=(32, 24))
        hero.pack(fill="x")
        ttk.Label(hero, text="V A U L T   /   PERSONAL ARCHIVE", style="Sub.TLabel").pack(
            anchor="w"
        )
        ttk.Label(hero, text="Lo importante, a salvo.", style="Title.TLabel").pack(
            anchor="w", pady=8
        )
        ttk.Label(
            hero,
            text="Respaldo cifrado · Versiones independientes · Restauración sin sobrescrituras",
        ).pack(anchor="w")
        body = ttk.Frame(root, padding=(32, 0))
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body, width=340, padding=(0, 0, 28, 0))
        left.pack(side="left", fill="y")
        self.source = field(left, "Carpeta de origen")
        ttk.Button(left, text="Elegir origen", command=lambda: self.choose(self.source)).pack(
            anchor="w", pady=5
        )
        self.destination = field(left, "Carpeta de respaldos")
        ttk.Button(left, text="Elegir destino", command=lambda: self.choose(self.destination)).pack(
            anchor="w", pady=5
        )
        self.password = field(left, "Contraseña de cifrado · mínimo 12 caracteres", secret=True)
        self.interval = field(left, "Repetir cada (minutos; 0 = manual)", "0")
        ttk.Button(left, text="Crear respaldo", command=self.backup).pack(fill="x", pady=(22, 8))
        ttk.Button(left, text="Activar programación", command=self.schedule).pack(fill="x", pady=5)
        ttk.Button(left, text="Restaurar un archivo .vault", command=self.recover).pack(
            fill="x", pady=5
        )
        ttk.Label(
            left,
            text="La contraseña vive solo en esta sesión.\nEl programa debe seguir abierto para\nejecutar respaldos programados.",
            wraplength=310,
        ).pack(anchor="w", pady=18)
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)
        ttk.Label(right, text="ARCHIVO DE VERSIONES", style="Sub.TLabel").pack(anchor="w", pady=12)
        self.tree = table(right, ("Fecha UTC", "Archivos", "Tamaño"), (180, 90, 100))
        self.status = tk.StringVar(
            value="Sin operaciones pendientes. Elige tus carpetas para comenzar."
        )
        ttk.Label(root, textvariable=self.status, padding=20, wraplength=950).pack(
            side="bottom", fill="x", before=body
        )
        self.refresh()
        root.after(1000, self.tick)

    def choose(self, variable):
        value = filedialog.askdirectory(parent=self.root)
        if value:
            variable.set(value)

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for created, path, files, size in self.history.all():
            self.tree.insert(
                "",
                "end",
                values=(created[:19].replace("T", " "), files, f"{size / 1024**2:.2f} MB"),
            )

    def backup(self):
        if self.busy:
            return
        source, destination, password = (
            self.source.get(),
            self.destination.get(),
            self.password.get(),
        )
        if not source or not destination:
            messagebox.showerror("Faltan carpetas", "Selecciona origen y destino.")
            return
        self.busy = True
        self.status.set("Creando respaldo… No cierres el programa.")

        def work():
            try:
                result = snapshot(source, destination, password)
                self.history.add(result)
                return result
            finally:
                self.busy = False

        def done(result):
            self.status.set("Respaldo creado: " + result["path"])
            self.refresh()

        self.tasks.run(work, done)

    def schedule(self):
        try:
            minutes = int(self.interval.get())
            if minutes < 0 or (minutes and minutes < 5):
                raise ValueError()
            if minutes and (
                len(self.password.get()) < 12 or not self.source.get() or not self.destination.get()
            ):
                raise ValueError()
            self.next_run = time.monotonic() + minutes * 60 if minutes else None
            self.status.set(
                "Programación activa mientras Vault esté abierto."
                if minutes
                else "Programación desactivada."
            )
        except ValueError:
            messagebox.showerror(
                "Revisar programación",
                "Configura carpetas y contraseña. Usa 0 o un intervalo de al menos 5 minutos.",
            )

    def tick(self):
        if self.next_run and time.monotonic() >= self.next_run and not self.busy:
            try:
                minutes = max(5, int(self.interval.get()))
                self.next_run = time.monotonic() + minutes * 60
                self.backup()
            except ValueError:
                self.next_run = None
        self.root.after(1000, self.tick)

    def recover(self):
        archive = filedialog.askopenfilename(filetypes=[("Vault", "*.vault")])
        if not archive:
            return
        parent = filedialog.askdirectory(
            title="Carpeta que recibirá una nueva subcarpeta restaurada"
        )
        if not parent:
            return
        import uuid
        from pathlib import Path

        target = Path(parent) / ("restaurado-" + uuid.uuid4().hex[:8])
        password = self.password.get()
        self.tasks.run(
            lambda: restore(archive, target, password),
            lambda result: self.status.set("Restaurado en " + str(result)),
        )


def main():
    root = tk.Tk()
    Vault(root)
    root.mainloop()
