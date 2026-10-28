import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk


def theme(root, bg, fg, accent):
    root.configure(bg=bg)
    root.minsize(850, 580)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=("Segoe UI", 10), background=bg, foreground=fg)
    style.configure("TFrame", background=bg)
    style.configure("TLabel", background=bg, foreground=fg)
    style.configure("Title.TLabel", font=("Segoe UI", 28, "bold"))
    style.configure("Sub.TLabel", font=("Segoe UI", 11), foreground=fg)
    style.configure("TButton", padding=(14, 7), background=accent, foreground="#152023")
    style.configure("TEntry", foreground="#19252b", fieldbackground="#ffffff")
    style.configure("TCombobox", foreground="#19252b", fieldbackground="#ffffff")
    style.map("TCombobox", foreground=[("readonly", "#19252b")])
    style.map("TButton", background=[("active", "#dce4e5")])
    style.configure(
        "Treeview",
        background="#ffffff",
        fieldbackground="#ffffff",
        foreground="#19252b",
        rowheight=30,
    )
    style.configure(
        "Treeview.Heading", background=accent, foreground="#152023", font=("Segoe UI", 10, "bold")
    )
    style.map("Treeview", background=[("selected", accent)], foreground=[("selected", "#152023")])


def table(parent, columns, widths=None):
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
    for i, col in enumerate(columns):
        tree.heading(col, text=col)
        tree.column(col, width=(widths[i] if widths else 150), minwidth=60)
    bar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=bar.set)
    tree.pack(side="left", fill="both", expand=True)
    bar.pack(side="right", fill="y")
    frame.pack(fill="both", expand=True, pady=12)
    return tree


def field(parent, label, value="", secret=False):
    ttk.Label(parent, text=label).pack(anchor="w", pady=(9, 3))
    variable = tk.StringVar(value=value)
    entry = ttk.Entry(parent, textvariable=variable, show="*" if secret else "")
    entry.pack(fill="x")
    return variable


class Tasks:
    def __init__(self, root):
        self.root = root
        self.messages = queue.Queue()
        root.after(100, self.poll)

    def run(self, work, done):
        def execute():
            try:
                self.messages.put((done, work(), None))
            except Exception as error:
                self.messages.put((done, None, error))

        threading.Thread(target=execute, daemon=True).start()

    def poll(self):
        while not self.messages.empty():
            done, result, error = self.messages.get()
            if error:
                messagebox.showerror("No se pudo completar", str(error), parent=self.root)
            else:
                done(result)
        self.root.after(100, self.poll)
