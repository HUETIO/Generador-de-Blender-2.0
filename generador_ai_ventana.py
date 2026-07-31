#!/usr/bin/env python3
"""
Ventana externa (tkinter) para el addon 'Generador AI de Objetos'.

Uso:
    1. Pulsa 'Instalar / Actualizar todo' para copiar el addon a Blender,
       instalar las librerias de IA y verificar que cargan.
    2. Abre Blender (reinicia si estaba abierto) y activa el addon
       'Generador AI de Objetos'.
    3. En el panel 'Generador AI' pulsa 'Iniciar Servidor'.
    4. Ejecuta este archivo:  python generador_ai_ventana.py
    5. Pulsa 'Conectar'.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

HOST_DEFECTO = "127.0.0.1"
PUERTO_DEFECTO = 8787
TIMEOUT = 300
_SIN_VENTANA = 0x08000000

PAQUETES_IA = ["openai", "anthropic", "google-generativeai"]

TIPOS = [
    ("CUSTOM", "Personalizado"),
    ("CHARACTER", "Personaje"),
    ("VEHICLE", "Vehiculo"),
    ("BUILDING", "Edificio"),
    ("FURNITURE", "Mueble"),
    ("WEAPON", "Arma"),
]
ESTILOS = [
    ("REALISTIC", "Realista"),
    ("CARTOON", "Cartoon"),
    ("LOWPOLY", "Low Poly"),
    ("SCIFI", "Ciencia Ficcion"),
    ("FANTASY", "Fantasia"),
]


def _detectar_blenders():
    import glob
    base_dirs = []
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        val = os.environ.get(var)
        if not val:
            continue
        base = os.path.join(val, "Programs") if var == "LOCALAPPDATA" else val
        base_dirs.append(base)
    resultados = []
    vistos = set()
    appdata = os.environ.get("APPDATA", "")
    for base in base_dirs:
        for carpeta in glob.glob(os.path.join(base, "Blender Foundation", "Blender*")):
            nombre = os.path.basename(carpeta).replace("Blender", "").strip()
            if not nombre or not nombre[0].isdigit():
                continue
            ver_corta = ".".join(nombre.split(".")[:2])
            python = os.path.join(carpeta, ver_corta, "python", "bin", "python.exe")
            if not os.path.isfile(python):
                python = os.path.join(carpeta, nombre, "python", "bin", "python.exe")
            if not os.path.isfile(python):
                continue
            if python in vistos:
                continue
            vistos.add(python)
            config = os.path.join(appdata, "Blender Foundation", "Blender", ver_corta)
            resultados.append({
                "version": ver_corta,
                "python": python,
                "exe": os.path.join(carpeta, "blender.exe") if os.path.isfile(os.path.join(carpeta, "blender.exe")) else "",
                "config": config,
                "addons": os.path.join(config, "scripts", "addons"),
            })
    resultados.sort(key=lambda i: i["version"], reverse=True)
    return resultados


class ClienteBlender:
    def __init__(self):
        self._sock = None
        self._lock = threading.Lock()
        self._id = 0

    @property
    def conectado(self):
        return self._sock is not None

    def conectar(self, host, puerto):
        self.desconectar()
        s = socket.create_connection((host, puerto), timeout=8)
        self._sock = s

    def desconectar(self):
        with self._lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None

    def enviar(self, accion, timeout=TIMEOUT, **kwargs):
        if self._sock is None:
            raise ConnectionError("No hay conexion con Blender.")
        req = {"action": accion, **kwargs}
        with self._lock:
            req["id"] = self._id
            self._id += 1
            self._sock.sendall((json.dumps(req) + "\n").encode("utf-8"))
            self._sock.settimeout(timeout)
            buffer = ""
            while True:
                datos = self._sock.recv(65536)
                if not datos:
                    raise ConnectionError("Blender cerro la conexion.")
                buffer += datos.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    linea, buffer = buffer.split("\n", 1)
                    if not linea.strip():
                        continue
                    resp = json.loads(linea)
                    if resp.get("id") == req["id"]:
                        return resp


class Ventana:
    def __init__(self, root):
        self.root = root
        self.root.title("Generador AI - Cliente Blender")
        self.root.geometry("560x820")
        self.root.minsize(500, 680)

        self.cliente = ClienteBlender()
        self.proveedores = {}
        self.proveedor_actual = "GEMINI"
        self.historial = []
        self._pid_por_label = {}
        self._label_por_pid = {}
        self._tipo_por_label = {l: p for p, l in TIPOS}
        self._estilo_por_label = {l: p for p, l in ESTILOS}

        self.blenders = []
        self.var_blender = tk.StringVar()

        self.var_host = tk.StringVar(value=HOST_DEFECTO)
        self.var_puerto = tk.StringVar(value=str(PUERTO_DEFECTO))
        self.var_proveedor = tk.StringVar()
        self.var_composicion = tk.BooleanVar(value=False)
        self.var_tipo = tk.StringVar(value="Personalizado")
        self.var_estilo = tk.StringVar(value="Realista")
        self.var_auto = tk.BooleanVar(value=False)

        self._construir_ui()
        self._set_estado("Conectate a Blender para empezar.")

    def _construir_ui(self):
        mono = ("Consolas", 9)
        self.root.option_add("*TCombobox*Listbox.font", mono)

        marco_conexion = ttk.LabelFrame(self.root, text=" Conexion con Blender ")
        marco_conexion.pack(fill="x", padx=8, pady=(8, 4))

        fila = ttk.Frame(marco_conexion)
        fila.pack(fill="x", padx=6, pady=4)
        ttk.Label(fila, text="Host:").pack(side="left")
        ttk.Entry(fila, textvariable=self.var_host, width=14).pack(side="left", padx=4)
        ttk.Label(fila, text="Puerto:").pack(side="left", padx=(8, 0))
        ttk.Entry(fila, textvariable=self.var_puerto, width=6).pack(side="left", padx=4)
        self.btn_conectar = ttk.Button(fila, text="Conectar", command=self.conectar)
        self.btn_conectar.pack(side="left", padx=8)
        self.lbl_version = ttk.Label(marco_conexion, text="")
        self.lbl_version.pack(anchor="w", padx=6)

        marco_instalar = ttk.LabelFrame(self.root, text=" Instalacion (addon y librerias de IA) ")
        marco_instalar.pack(fill="x", padx=8, pady=4)

        fila = ttk.Frame(marco_instalar)
        fila.pack(fill="x", padx=6, pady=(4, 0))
        ttk.Label(fila, text="Blender:").pack(side="left")
        self.cmb_blender = ttk.Combobox(fila, textvariable=self.var_blender, state="readonly")
        self.cmb_blender.pack(side="left", fill="x", expand=True, padx=4)
        self.btn_buscar = ttk.Button(fila, text="Buscar...", command=self.buscar_blender, width=10)
        self.btn_buscar.pack(side="left")

        fila2 = ttk.Frame(marco_instalar)
        fila2.pack(fill="x", padx=6, pady=4)
        self.btn_instalar = ttk.Button(fila2, text="Instalar / Actualizar todo", command=self.instalar_todo)
        self.btn_instalar.pack(side="left")
        self.btn_verificar = ttk.Button(fila2, text="Verificar", command=self.verificar)
        self.btn_verificar.pack(side="left", padx=8)
        self.lbl_instalar = ttk.Label(marco_instalar, text="")
        self.lbl_instalar.pack(anchor="w", padx=6, pady=(0, 4))

        self._refrescar_blenders()
        self._actualizar_combo_blender()

        marco_proveedor = ttk.LabelFrame(self.root, text=" Proveedor IA ")
        marco_proveedor.pack(fill="x", padx=8, pady=4)
        fila = ttk.Frame(marco_proveedor)
        fila.pack(fill="x", padx=6, pady=4)
        ttk.Label(fila, text="Proveedor:").pack(side="left")
        self.cmb_proveedor = ttk.Combobox(fila, textvariable=self.var_proveedor, state="readonly", width=34)
        self.cmb_proveedor.pack(side="left", padx=6)
        ttk.Button(fila, text="Refrescar", command=self.refrescar).pack(side="left")
        self.lbl_prov_info = ttk.Label(marco_proveedor, text="", wraplength=520)
        self.lbl_prov_info.pack(anchor="w", padx=6, pady=(0, 4))

        marco_prompt = ttk.LabelFrame(self.root, text=" Prompt ")
        marco_prompt.pack(fill="x", padx=8, pady=4)
        self.txt_prompt = tk.Text(marco_prompt, height=5, wrap="word", font=mono)
        self.txt_prompt.pack(fill="x", padx=6, pady=4)
        self.cb_composicion = ttk.Checkbutton(marco_prompt, text="Usar composicion",
                                              variable=self.var_composicion, command=self._actualizar_composicion)
        self.cb_composicion.pack(anchor="w", padx=6)
        fila = ttk.Frame(marco_prompt)
        fila.pack(fill="x", padx=6)
        self.lbl_tipo = ttk.Label(fila, text="Tipo:")
        self.lbl_tipo.pack(side="left")
        self.cmb_tipo = ttk.Combobox(fila, textvariable=self.var_tipo, state="disabled", width=16,
                                     values=[l for _, l in TIPOS])
        self.cmb_tipo.pack(side="left", padx=4)
        self.lbl_estilo = ttk.Label(fila, text="Estilo:")
        self.lbl_estilo.pack(side="left", padx=(8, 0))
        self.cmb_estilo = ttk.Combobox(fila, textvariable=self.var_estilo, state="disabled", width=14,
                                       values=[l for _, l in ESTILOS])
        self.cmb_estilo.pack(side="left", padx=4)
        fila = ttk.Frame(marco_prompt)
        fila.pack(fill="x", padx=6, pady=4)
        self.cb_auto = ttk.Checkbutton(fila, text="Auto-ejecutar tras generar", variable=self.var_auto)
        self.cb_auto.pack(side="left")
        self.btn_generar = ttk.Button(fila, text="Generar Comandos", command=self.generar)
        self.btn_generar.pack(side="right")

        marco_comandos = ttk.LabelFrame(self.root, text=" Comandos JSON ")
        marco_comandos.pack(fill="both", expand=True, padx=8, pady=4)
        self.txt_comandos = tk.Text(marco_comandos, height=12, wrap="none", font=mono)
        self.txt_comandos.pack(fill="both", expand=True, padx=6, pady=4)
        fila = ttk.Frame(marco_comandos)
        fila.pack(fill="x", padx=6, pady=(0, 4))
        self.btn_validar = ttk.Button(fila, text="Validar", command=self.validar)
        self.btn_validar.pack(side="left")
        self.btn_ejecutar = ttk.Button(fila, text="Ejecutar", command=self.ejecutar)
        self.btn_ejecutar.pack(side="left", padx=4)
        self.btn_limpiar = ttk.Button(fila, text="Limpiar", command=self.limpiar)
        self.btn_limpiar.pack(side="left", padx=4)
        ttk.Label(fila, text="Refinar:").pack(side="left", padx=(12, 4))
        self.var_refinar = tk.StringVar()
        self.ent_refinar = ttk.Entry(fila, textvariable=self.var_refinar)
        self.ent_refinar.pack(side="left", fill="x", expand=True)
        self.btn_refinar = ttk.Button(fila, text="Refinar", command=self.refinar)
        self.btn_refinar.pack(side="left", padx=4)

        marco_historial = ttk.LabelFrame(self.root, text=" Historial ")
        marco_historial.pack(fill="both", padx=8, pady=4)
        self.lst_historial = tk.Listbox(marco_historial, height=5, font=("Consolas", 9))
        self.lst_historial.pack(fill="both", expand=True, padx=6, pady=4)
        self.lst_historial.bind("<Double-Button-1>", lambda e: self.cargar_historial())
        fila = ttk.Frame(marco_historial)
        fila.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Button(fila, text="Cargar seleccion", command=self.cargar_historial).pack(side="left")
        ttk.Button(fila, text="Vaciar historial", command=self.vaciar_historial).pack(side="left", padx=4)

        marco_log = ttk.LabelFrame(self.root, text=" Registro ")
        marco_log.pack(fill="both", expand=True, padx=8, pady=(4, 0))
        self.txt_log = tk.Text(marco_log, height=5, wrap="word", state="disabled", font=("Consolas", 8))
        self.txt_log.pack(fill="both", expand=True, padx=6, pady=4)

        self.lbl_estado = ttk.Label(self.root, text="", relief="sunken", anchor="w")
        self.lbl_estado.pack(fill="x", side="bottom")

        self.root.protocol("WM_DELETE_WINDOW", self._cerrar)

    def _actualizar_composicion(self):
        estado = "readonly" if self.var_composicion.get() else "disabled"
        self.cmb_tipo.config(state=estado)
        self.cmb_estilo.config(state=estado)

    def _set_estado(self, texto, error=False):
        self.lbl_estado.config(text=texto, foreground="#c00000" if error else "#0a0a0a")
        self._log(texto)

    def _log(self, texto):
        self.txt_log.config(state="normal")
        self.txt_log.insert("end", texto + "\n")
        self.txt_log.see("end")
        self.txt_log.config(state="disabled")

    def _en_hilo(self, tarea, on_ok, on_err=None):
        def trabajo():
            try:
                resp = tarea()
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda m=msg: (on_err or self._error)(m))
                return
            self.root.after(0, lambda r=resp: on_ok(r))
        threading.Thread(target=trabajo, daemon=True).start()

    def _error(self, msg):
        self._set_estado(msg, error=True)
        self.btn_conectar.config(text="Conectar")

    def _requiere_conexion(self):
        if not self.cliente.conectado:
            messagebox.showerror("Sin conexion", "Primero conectate a Blender.")
            return False
        return True

    def _pid_seleccionado(self):
        return self._pid_por_label.get(self.var_proveedor.get(), self.proveedor_actual)

    # --- Instalacion ---
    def _refrescar_blenders(self):
        self.blenders = _detectar_blenders()

    def _actualizar_combo_blender(self):
        nombres = []
        for b in self.blenders:
            etiqueta = f"Blender {b['version']}"
            self.var_blender.set(etiqueta)
            self.cmb_blender["values"] = [f"Blender {x['version']}" for x in self.blenders]
            break
        if not self.blenders:
            self.var_blender.set("Blender no detectado - usa Buscar...")
            self.cmb_blender["values"] = []

    def _blender_seleccionado(self):
        idx = self.cmb_blender.current()
        if idx < 0 or idx >= len(self.blenders):
            return None
        return self.blenders[idx]

    def _set_instalar(self, texto):
        self.lbl_instalar.config(text=texto)

    def _verificar(self, b, target):
        if not os.path.isfile(b.get("exe", "")):
            codigo = (
                "import sys; sys.path.insert(0, %r);"
                "import google.generativeai, openai, anthropic; print('LIBS_OK')" % target
            )
            r = subprocess.run([b["python"], "-c", codigo], capture_output=True, text=True,
                               creationflags=_SIN_VENTANA, timeout=600)
            if r.returncode == 0 and "LIBS_OK" in r.stdout:
                return True, "Librerias instaladas correctamente (verificadas con el Python de Blender)."
            return False, "Las librerias no se importan:\n" + (r.stderr or r.stdout)[-800:]
        addon_py = os.path.join(b["addons"], "mi_addon.py")
        script = (
            "import importlib.util;\n"
            "spec = importlib.util.spec_from_file_location('verify_addon', %r);\n"
            "m = importlib.util.module_from_spec(spec);\n"
            "spec.loader.exec_module(m);\n"
            "print('ADDON_LIBS:', m.LIB_GOOGLE, m.LIB_OPENAI, m.LIB_ANTHROPIC)" % addon_py
        )
        r = subprocess.run([b["exe"], "--background", "--python-expr", script], capture_output=True,
                           text=True, creationflags=_SIN_VENTANA, timeout=600)
        if "ADDON_LIBS:" in r.stdout:
            linea = next((l for l in r.stdout.splitlines() if "ADDON_LIBS:" in l), "")
            flags = linea.split(":", 1)[1].split() if ":" in linea else []
            if all(f == "True" for f in flags):
                return True, "Todo verificado en Blender: addon y librerias (Google, OpenAI, Anthropic) cargan bien."
            return False, "Blender no carga todas las librerias. Reinicia Blender y verifica de nuevo.\n" + r.stdout[-600:]
        return False, "No se pudo verificar dentro de Blender:\n" + (r.stderr or r.stdout)[-600:]

    def instalar_todo(self):
        b = self._blender_seleccionado()
        if b is None:
            messagebox.showerror("Blender no detectado",
                                 "No se encontro Blender. Usa 'Buscar...' para localizar su python.exe.")
            return
        self.btn_instalar.config(state="disabled")
        self.btn_verificar.config(state="disabled")
        self._set_estado("Instalando... puede tardar unos minutos.")
        self._set_instalar("Instalando librerias (openai, anthropic, google-generativeai)...")

        def tarea():
            pasos = []
            dir_actual = os.path.dirname(os.path.abspath(__file__))
            origen = os.path.join(dir_actual, "mi_addon.py")
            os.makedirs(b["addons"], exist_ok=True)
            if os.path.isfile(origen):
                shutil.copy2(origen, os.path.join(b["addons"], "mi_addon.py"))
                pasos.append("Addon copiado a Blender (version actual).")
            else:
                pasos.append("AVISO: no hay mi_addon.py junto a la ventana; el addon no se actualizo.")
            origen_ventana = os.path.join(dir_actual, "generador_ai_ventana.py")
            if os.path.isfile(origen_ventana):
                shutil.copy2(origen_ventana, os.path.join(b["addons"], "generador_ai_ventana.py"))
                pasos.append("Ventana cliente copiada a Blender (el boton del addon la puede abrir).")
            else:
                pasos.append("AVISO: no hay generador_ai_ventana.py junto al addon; el boton no podra abrirla.")
            target = os.path.join(b["config"], "python_site")
            comando = [b["python"], "-m", "pip", "install", "--disable-pip-version-check",
                       "--target", target] + PAQUETES_IA
            r = subprocess.run(comando, capture_output=True, text=True,
                               creationflags=_SIN_VENTANA, timeout=1800)
            if r.returncode != 0:
                raise RuntimeError("pip fallo:\n" + (r.stdout + r.stderr)[-1500:])
            pasos.append("Librerias de IA instaladas en python_site.")
            okv, msgv = self._verificar(b, target)
            pasos.append(msgv)
            if not okv:
                pasos.append("CONSEJO: si las librerias ya estaban en el Python del sistema,"
                             " inicia Blender con: blender --python-use-system-env")
            return "\n".join(pasos), okv

        def ok(resultado):
            self.btn_instalar.config(state="normal")
            self.btn_verificar.config(state="normal")
            texto, okv = resultado
            self._log(texto)
            if okv:
                self._set_estado("Instalacion completada. Reinicia Blender para cargar el addon nuevo.")
            else:
                self._set_estado("Instalacion terminada con advertencias. Mira el log.", error=True)
            self._set_instalar("Listo. Reinicia Blender.")

        def err(msg):
            self.btn_instalar.config(state="normal")
            self.btn_verificar.config(state="normal")
            self._set_estado("Instalacion fallo: " + msg, error=True)
            self._set_instalar("")

        self._en_hilo(tarea, ok, err)

    def verificar(self):
        b = self._blender_seleccionado()
        if b is None:
            messagebox.showerror("Blender no detectado",
                                 "No se encontro Blender. Usa 'Buscar...' para localizar su python.exe.")
            return
        self.btn_verificar.config(state="disabled")
        self._set_estado("Verificando...")

        def tarea():
            return self._verificar(b, os.path.join(b["config"], "python_site"))

        def ok(resp):
            self.btn_verificar.config(state="normal")
            okv, msg = resp
            self._set_estado(msg, error=not okv)
            self._log(msg)

        def err(msg):
            self.btn_verificar.config(state="normal")
            self._set_estado("Verificacion fallo: " + msg, error=True)

        self._en_hilo(tarea, ok, err)

    def buscar_blender(self):
        path = filedialog.askopenfilename(
            title="Selecciona el python.exe de Blender",
            filetypes=[("Python de Blender", "python.exe"), ("Todos los archivos", "*.*")])
        if not path:
            return
        partes = os.path.normpath(path).split(os.sep)
        ver = ""
        for p in partes:
            if p.lower().startswith("blender "):
                ver = ".".join(p.replace("Blender", "").strip().split(".")[:2])
                break
        if not ver:
            messagebox.showerror("No valido", "La ruta no contiene una carpeta 'Blender X.Y'.")
            return
        carpeta = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(path))))
        exe = os.path.join(carpeta, "blender.exe")
        config = os.path.join(os.environ.get("APPDATA", ""), "Blender Foundation", "Blender", ver)
        item = {"version": ver, "python": path,
                "exe": exe if os.path.isfile(exe) else "",
                "config": config, "addons": os.path.join(config, "scripts", "addons")}
        self.blenders = [i for i in self.blenders if i["python"] != path]
        self.blenders.insert(0, item)
        self.cmb_blender["values"] = [f"Blender {x['version']}" for x in self.blenders]
        self.var_blender.set(f"Blender {ver}")
        self._set_estado(f"Blender {ver} seleccionado para la instalacion.")

    # --- Acciones ---
    def conectar(self):
        if self.cliente.conectado:
            self.desconectar()
            return
        host = self.var_host.get().strip() or HOST_DEFECTO
        try:
            puerto = int(self.var_puerto.get() or str(PUERTO_DEFECTO))
        except ValueError:
            messagebox.showerror("Puerto invalido", "El puerto debe ser un numero entero.")
            return
        self.btn_conectar.config(state="disabled")
        self._set_estado("Conectando...")

        def tarea():
            self.cliente.conectar(host, puerto)
            return self.cliente.enviar("get_state")

        def ok(resp):
            self.btn_conectar.config(state="normal", text="Desconectar")
            if resp.get("ok"):
                data = resp.get("data", {})
                version = data.get("version", {})
                self.lbl_version.config(
                    text=f"Blender {version.get('blender', '?')} | addon v{version.get('addon', '?')}")
                self._cargar_proveedores(data.get("providers", {}))
                self.proveedor_actual = data.get("provider", "GEMINI")
                self.historial = data.get("history", [])
                self._rellenar_historial()
                if data.get("ai_commands_json"):
                    self._poner_comandos(data["ai_commands_json"])
                self._set_estado("Conectado a Blender.")
            else:
                self._set_estado("Error: " + resp.get("error", "desconocido"), error=True)

        def err(msg):
            self.btn_conectar.config(state="normal")
            self._set_estado(f"No se pudo conectar: {msg}", error=True)

        self._en_hilo(tarea, ok, err)

    def desconectar(self):
        self.cliente.desconectar()
        self.btn_conectar.config(text="Conectar")
        self.lbl_version.config(text="")
        self._set_estado("Desconectado.")

    def refrescar(self):
        if not self._requiere_conexion():
            return
        self._en_hilo(lambda: self.cliente.enviar("get_state"),
                      lambda resp: (self._cargar_proveedores(resp["data"]["providers"]),
                                    self._set_estado("Estado refrescado.")) if resp.get("ok") else
                                  self._set_estado("Error: " + resp.get("error", ""), error=True))

    def _cargar_proveedores(self, provs):
        self.proveedores = provs or {}
        self._pid_por_label = {}
        self._label_por_pid = {}
        opciones = []
        for pid, info in self.proveedores.items():
            etiqueta = info.get("label", pid)
            self._pid_por_label[etiqueta] = pid
            self._label_por_pid[pid] = etiqueta
            opciones.append(etiqueta)
        self.cmb_proveedor["values"] = opciones
        if opciones:
            actual = self._label_por_pid.get(self.proveedor_actual, opciones[0])
            self.var_proveedor.set(actual)
        partes = [f"{info.get('label', pid)}: {'OK' if info.get('available') else 'falta libreria'}"
                  for pid, info in self.proveedores.items()]
        self.lbl_prov_info.config(text="  |  ".join(partes))

    def generar(self):
        if not self._requiere_conexion():
            return
        prompt = self.txt_prompt.get("1.0", "end").strip()
        if not prompt:
            messagebox.showerror("Prompt vacio", "Escribe un prompt primero.")
            return
        pid = self._pid_seleccionado()
        composicion = bool(self.var_composicion.get())
        tipo = self._tipo_por_label.get(self.var_tipo.get(), "CUSTOM")
        estilo = self._estilo_por_label.get(self.var_estilo.get(), "REALISTIC")
        auto = bool(self.var_auto.get())
        self.btn_generar.config(state="disabled")
        self._set_estado("Generando con IA... puede tardar unos segundos.")

        def tarea():
            return self.cliente.enviar("generate", prompt=prompt, provider=pid,
                                       use_composition=composicion, composition_type=tipo,
                                       composition_style=estilo, auto_execute=auto)

        def ok(resp):
            self.btn_generar.config(state="normal")
            if resp.get("ok"):
                data = resp["data"]
                self._poner_comandos(data["commands_json"])
                estado = data.get("status", "")
                if data.get("executed"):
                    estado += "  (comandos ejecutados)"
                self._set_estado(estado)
                self._refrescar_historial()
            else:
                self._set_estado("Error: " + resp.get("error", "desconocido"), error=True)
                for m in resp.get("messages", []):
                    self._log("  " + m)

        def err(msg):
            self.btn_generar.config(state="normal")
            self._set_estado(msg, error=True)

        self._en_hilo(tarea, ok, err)

    def validar(self):
        if not self._requiere_conexion():
            return
        comandos = self._comandos_actuales()
        if not comandos:
            messagebox.showerror("Sin comandos", "No hay comandos que validar.")
            return

        def tarea():
            return self.cliente.enviar("preview", commands_json=comandos)

        def ok(resp):
            if resp.get("ok"):
                data = resp["data"]
                resumen = ", ".join(f"{k}: {v}" for k, v in data.get("summary", {}).items())
                self._set_estado(f"JSON valido. {data['count']} comandos. {resumen}")
            else:
                self._set_estado("Error: " + resp.get("error", ""), error=True)

        self._en_hilo(tarea, ok)

    def ejecutar(self):
        if not self._requiere_conexion():
            return
        comandos = self._comandos_actuales()
        if not comandos:
            messagebox.showerror("Sin comandos", "No hay comandos que ejecutar.")
            return
        self.btn_ejecutar.config(state="disabled")
        self._set_estado("Ejecutando en Blender...")

        def tarea():
            return self.cliente.enviar("execute", commands_json=comandos)

        def ok(resp):
            self.btn_ejecutar.config(state="normal")
            if resp.get("ok"):
                self._set_estado("Comandos ejecutados en Blender.")
                self._refrescar_historial()
            else:
                self._set_estado("Error: " + resp.get("error", ""), error=True)

        def err(msg):
            self.btn_ejecutar.config(state="normal")
            self._set_estado(msg, error=True)

        self._en_hilo(tarea, ok, err)

    def refinar(self):
        if not self._requiere_conexion():
            return
        instruccion = self.var_refinar.get().strip()
        comandos = self._comandos_actuales()
        if not instruccion:
            messagebox.showerror("Instruccion vacia", "Escribe que quieres refinar.")
            return
        if not comandos:
            messagebox.showerror("Sin comandos", "Genera comandos antes de refinar.")
            return
        self.btn_refinar.config(state="disabled")
        self._set_estado("Refinando con IA...")

        def tarea():
            return self.cliente.enviar("refine", instruction=instruccion, commands_json=comandos,
                                       provider=self._pid_seleccionado())

        def ok(resp):
            self.btn_refinar.config(state="normal")
            if resp.get("ok"):
                data = resp["data"]
                self._poner_comandos(data["commands_json"])
                self._set_estado(data.get("status", ""))
                self._refrescar_historial()
            else:
                self._set_estado("Error: " + resp.get("error", ""), error=True)

        def err(msg):
            self.btn_refinar.config(state="normal")
            self._set_estado(msg, error=True)

        self._en_hilo(tarea, ok, err)

    def limpiar(self):
        self.txt_comandos.delete("1.0", "end")
        self.var_refinar.set("")
        if not self.cliente.conectado:
            return
        self._en_hilo(lambda: self.cliente.enviar("clear"),
                      lambda resp: self._set_estado("Comandos borrados.") if resp.get("ok")
                      else self._set_estado("Error: " + resp.get("error", ""), error=True))

    def cargar_historial(self):
        idx = self.lst_historial.curselection()
        if not idx:
            return
        item = self.historial[int(idx[0])]
        self.txt_prompt.delete("1.0", "end")
        self.txt_prompt.insert("1.0", item.get("prompt", ""))
        self._poner_comandos(item.get("json_text", ""))
        self._set_estado("Historial cargado en prompt y comandos.")

    def vaciar_historial(self):
        if not self._requiere_conexion():
            return
        self._en_hilo(lambda: self.cliente.enviar("clear_history"),
                      lambda resp: (self._refrescar_historial(),
                                    self._set_estado("Historial vaciado.")) if resp.get("ok")
                      else self._set_estado("Error: " + resp.get("error", ""), error=True))

    # --- Utilidades de UI ---
    def _comandos_actuales(self):
        return self.txt_comandos.get("1.0", "end").strip()

    def _poner_comandos(self, texto):
        self.txt_comandos.delete("1.0", "end")
        self.txt_comandos.insert("1.0", texto)

    def _refrescar_historial(self):
        if not self.cliente.conectado:
            return
        self._en_hilo(lambda: self.cliente.enviar("get_state"),
                      lambda resp: self._cargar_historial_desde(resp) if resp.get("ok") else None)

    def _cargar_historial_desde(self, resp):
        self.historial = resp["data"].get("history", [])
        self._rellenar_historial()

    def _rellenar_historial(self):
        self.lst_historial.delete(0, "end")
        for h in self.historial:
            self.lst_historial.insert("end", f"[{h.get('timestamp', '')}] {h.get('status', '')}: {h.get('prompt', '')[:50]}")

    def _cerrar(self):
        self.cliente.desconectar()
        self.root.destroy()


def main():
    root = tk.Tk()
    Ventana(root)
    root.mainloop()


if __name__ == "__main__":
    main()
