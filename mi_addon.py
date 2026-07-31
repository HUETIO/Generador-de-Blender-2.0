bl_info = {
    "name": "Generador AI de Objetos",
    "blender": (3, 0, 0),
    "category": "Object",
    "author": "Tu Nombre",
    "version": (2, 0, 0),
    "location": "View3D > Sidebar > Generador AI",
    "description": "Crea objetos en Blender usando prompts con multiples proveedores de IA (Gemini, OpenAI, Claude, OpenAI Compatible)",
    "warning": "Requiere una API Key de al menos un proveedor, la libreria correspondiente y conexion a internet.",
    "doc_url": "",
    "tracker_url": "",
}

import bpy
import os
import sys
import json
import time
import socket
import subprocess
import threading
import queue


def _lib_disponible(mod):
    try:
        __import__(mod)
        return True
    except ImportError:
        return False


def _agregar_rutas_librerias():
    import os
    import sys as _sys
    import site as _site
    candidatos = []
    appdata = os.environ.get("APPDATA", "")
    try:
        version = f"{bpy.app.version[0]}.{bpy.app.version[1]}"
    except Exception:
        version = ""
    if appdata and version:
        candidatos.append(os.path.join(appdata, "Blender Foundation", "Blender", version, "python_site"))
    try:
        usuario = _site.getusersitepackages()
        if usuario:
            candidatos.append(usuario)
    except Exception:
        pass
    for ruta in candidatos:
        if ruta and os.path.isdir(ruta) and ruta not in _sys.path:
            _sys.path.insert(0, ruta)


_agregar_rutas_librerias()

LIB_GOOGLE = _lib_disponible("google.generativeai")
LIB_OPENAI = _lib_disponible("openai")
LIB_ANTHROPIC = _lib_disponible("anthropic")


def _provider_items(self, context):
    return [
        ("GEMINI", "Google Gemini", "Google Gemini (requiere google-generativeai)"),
        ("OPENAI", "OpenAI", "OpenAI GPT (requiere openai)"),
        ("ANTHROPIC", "Anthropic Claude", "Anthropic Claude (requiere anthropic)"),
        ("OPENAI_COMPATIBLE", "LM Studio (OpenAI Compatible)", "LM Studio, vLLM, OpenRouter, LocalAI... (requiere openai)"),
    ]


class AIProviderBase:
    id = ""
    label = ""
    lib_name = ""
    model_default = ""
    key_prop = ""
    model_prop = ""
    base_prop = ""
    needs_base_url = False
    no_key_required = False

    def __init__(self, api_key, model, base_url=""):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    @classmethod
    def available(cls):
        return True

    def generate(self, system_prompt, user_prompt):
        raise NotImplementedError


class GeminiProvider(AIProviderBase):
    id = "GEMINI"
    label = "Google Gemini"
    lib_name = "google.generativeai"
    model_default = "gemini-3.5-flash"
    key_prop = "gemini_api_key"
    model_prop = "gemini_model"

    @classmethod
    def available(cls):
        return LIB_GOOGLE

    def generate(self, system_prompt, user_prompt):
        import google.generativeai as genai
        genai.configure(api_key=self.api_key)
        try:
            model = genai.GenerativeModel(self.model, system_instruction=system_prompt)
        except TypeError:
            model = genai.GenerativeModel(self.model)
            user_prompt = system_prompt + "\n\n" + user_prompt
        response = model.generate_content(user_prompt)
        return response.text


class OpenAIProvider(AIProviderBase):
    id = "OPENAI"
    label = "OpenAI"
    lib_name = "openai"
    model_default = "gpt-4o-mini"
    key_prop = "openai_api_key"
    model_prop = "openai_model"

    @classmethod
    def available(cls):
        return LIB_OPENAI

    def generate(self, system_prompt, user_prompt):
        from openai import OpenAI
        client = OpenAI(api_key=self.api_key)
        response = client.chat.completions.create(
            model=self.model,
            temperature=0.6,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content or ""


class AnthropicProvider(AIProviderBase):
    id = "ANTHROPIC"
    label = "Anthropic Claude"
    lib_name = "anthropic"
    model_default = "claude-3-5-haiku-latest"
    key_prop = "anthropic_api_key"
    model_prop = "anthropic_model"

    @classmethod
    def available(cls):
        return LIB_ANTHROPIC

    def generate(self, system_prompt, user_prompt):
        from anthropic import Anthropic
        client = Anthropic(api_key=self.api_key)
        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            temperature=0.6,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return "".join(b.text for b in response.content if getattr(b, "type", "") == "text")


class OpenAICompatibleProvider(AIProviderBase):
    id = "OPENAI_COMPATIBLE"
    label = "LM Studio / OpenAI Compatible"
    lib_name = "openai"
    model_default = "local-model"
    key_prop = "compatible_api_key"
    model_prop = "compatible_model"
    base_prop = "compatible_base_url"
    needs_base_url = True
    no_key_required = True
    base_url_default = "http://localhost:1234/v1"

    @classmethod
    def available(cls):
        return LIB_OPENAI

    def generate(self, system_prompt, user_prompt):
        from openai import OpenAI
        client = OpenAI(api_key=self.api_key or "lm-studio", base_url=self.base_url or self.base_url_default)
        response = client.chat.completions.create(
            model=self.model,
            temperature=0.6,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content or ""


PROVIDERS = {
    cls.id: cls
    for cls in (GeminiProvider, OpenAIProvider, AnthropicProvider, OpenAICompatibleProvider)
}

# --- Modelos Gemini disponibles (API de Google, 2026) ---
GEMINI_MODELS = [
    ("gemini-3.6-flash", "Gemini 3.6 Flash", "Ultimo modelo GA, rapido y economico"),
    ("gemini-3.5-flash", "Gemini 3.5 Flash", "Recomendado, rapido y capaz"),
    ("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", "El mas rapido y economico de la familia 3.5"),
    ("gemini-2.5-flash", "Gemini 2.5 Flash", "Version anterior, rapida"),
    ("gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite", "Version anterior, economica"),
    ("gemini-2.5-pro", "Gemini 2.5 Pro", "Razonamiento avanzado"),
]

# --- Preferencias del Add-on ---
class GeneradorAIPreferencias(bpy.types.AddonPreferences):
    bl_idname = __name__

    gemini_api_key: bpy.props.StringProperty(name="Gemini API Key", subtype='PASSWORD')
    openai_api_key: bpy.props.StringProperty(name="OpenAI API Key", subtype='PASSWORD')
    anthropic_api_key: bpy.props.StringProperty(name="Anthropic API Key", subtype='PASSWORD')
    compatible_api_key: bpy.props.StringProperty(name="OpenAI Compatible API Key", subtype='PASSWORD')

    gemini_model: bpy.props.EnumProperty(
        name="Modelo",
        description="Modelo de Google Gemini a usar",
        items=GEMINI_MODELS,
        default="gemini-3.5-flash",
    )
    openai_model: bpy.props.StringProperty(name="Modelo", default="gpt-4o-mini")
    anthropic_model: bpy.props.StringProperty(name="Modelo", default="claude-3-5-haiku-latest")
    compatible_model: bpy.props.StringProperty(name="Modelo", default="local-model")

    compatible_base_url: bpy.props.StringProperty(
        name="Base URL",
        description="URL compatible con la API de OpenAI (LM Studio usa http://localhost:1234/v1)",
        default="http://localhost:1234/v1",
    )

    use_fallback: bpy.props.BoolProperty(
        name="Reintentar con otros proveedores",
        description="Si el proveedor seleccionado falla, probar con los demas que tengan API Key configurada",
        default=True,
    )

    server_port: bpy.props.IntProperty(
        name="Puerto del servidor",
        description="Puerto TCP local para la ventana externa (tkinter)",
        default=8787,
        min=1024,
        max=65535,
    )

    def draw(self, context):
        layout = self.layout

        box = layout.box()
        box.label(text="Proveedores:", icon='WORLD_DATA')
        for cls in PROVIDERS.values():
            sub = box.box()
            col = sub.column(align=True)
            if cls.available():
                col.label(text=f"{cls.label}  -  libreria instalada", icon='CHECKMARK')
            else:
                col.label(text=f"{cls.label}  -  falta la libreria '{cls.lib_name}'", icon='ERROR')
            col.prop(self, cls.key_prop)
            col.prop(self, cls.model_prop)
            if getattr(cls, "needs_base_url", False):
                col.prop(self, cls.base_prop)

        box = layout.box()
        box.label(text="Opciones:", icon='SETTINGS')
        box.prop(self, "use_fallback")
        box.prop(self, "server_port")

        if not (LIB_GOOGLE or LIB_OPENAI or LIB_ANTHROPIC):
            col = layout.column(align=True)
            col.label(text="No se encontro ninguna libreria de IA instalada.", icon='ERROR')
            col.label(text=f"Python de Blender: {sys.executable}")
            col.label(text="Instala al menos una con, por ejemplo:")
            col.label(text=f"  \"{sys.executable}\" -m pip install google-generativeai openai anthropic")
            col.label(text="Despues reinicia Blender completamente.")


# --- Modelo de historial ---
class HistoriaItem(bpy.types.PropertyGroup):
    prompt: bpy.props.StringProperty()
    json_text: bpy.props.StringProperty()
    provider: bpy.props.StringProperty()
    status: bpy.props.StringProperty()
    timestamp: bpy.props.StringProperty()


# --- Utilidades ---
def get_provider(prefs, provider_id):
    cls = PROVIDERS.get(provider_id)
    if cls is None or not cls.available():
        return None
    return cls(
        api_key=getattr(prefs, cls.key_prop, "") or "",
        model=getattr(prefs, cls.model_prop, "") or cls.model_default,
        base_url=getattr(prefs, cls.base_prop, "") if getattr(cls, "needs_base_url", False) else "",
    )


def generar_texto(context, system_prompt, user_prompt, provider_id, report):
    prefs = context.preferences.addons[__name__].preferences
    orden = [provider_id]
    if getattr(prefs, "use_fallback", True):
        orden += [pid for pid in PROVIDERS if pid != provider_id]

    errores = []
    for pid in orden:
        cls = PROVIDERS.get(pid)
        if cls is None:
            continue
        if not cls.available():
            errores.append(f"{cls.label}: falta la libreria '{cls.lib_name}'")
            continue
        provider = get_provider(prefs, pid)
        if provider is None:
            continue
        if not provider.api_key and not getattr(cls, "no_key_required", False):
            if pid == provider_id:
                errores.append(f"{cls.label}: API Key no configurada en Preferencias")
            continue
        try:
            texto = provider.generate(system_prompt, user_prompt)
            if texto and texto.strip():
                return (pid, texto)
        except Exception as e:
            errores.append(f"{cls.label}: {e}")
            print(f"Error con {cls.label}: {e}")

    if errores:
        report({'ERROR'}, " | ".join(errores[:3]))
    else:
        report({'ERROR'}, "No hay ningun proveedor configurado.")
    return None


def limpiar_json(texto):
    t = texto.strip()
    if t.startswith("```"):
        lineas = t.splitlines()
        if lineas and lineas[0].strip().startswith("```"):
            lineas = lineas[1:]
        if lineas and lineas[-1].strip() == "```":
            lineas = lineas[:-1]
        t = "\n".join(lineas).strip()
    if not t:
        return t
    inicio = t.find("[")
    fin = t.rfind("]")
    if inicio != -1 and fin != -1 and fin > inicio:
        t = t[inicio:fin + 1]
    return t


def construir_prompt_sistema(scene):
    comp = ""
    if scene.use_composition and scene.composition_type != 'CUSTOM':
        comp = f"""
IMPORTANTE: El usuario quiere crear un objeto compuesto del tipo '{scene.composition_type}' con estilo '{scene.composition_style}'.
Debes descomponer este objeto en sus partes basicas y crear cada parte con los comandos disponibles.
Asegurate de que todas las partes esten correctamente posicionadas y dimensionadas para formar un objeto coherente.
"""
    return f"""
Tu tarea es interpretar el siguiente prompt del usuario y generar una lista JSON de comandos simples para crear y modificar objetos 3D en Blender.
Debes responder SOLO con la lista JSON valida. No incluyas explicaciones, comentarios, ni marcadores ```json```.
Si el prompt es ambiguo, inseguro, o pide algo fuera de las capacidades listadas, devuelve una lista JSON vacia: [].

{comp}

IMPORTANTE: El usuario puede dar prompts generales como "crea una espada de diamante" o "haz una casa de madera".
En estos casos, debes descomponer el objeto en partes basicas y crear cada parte con los comandos disponibles.
Usa tu conocimiento para interpretar el prompt y crear una representacion adecuada.

EJEMPLOS DE PROMPTS Y RESPUESTAS:

1. Prompt: "crea una espada de diamante"
   Respuesta: [
     {{"command": "add_primitive", "type": "cube", "size": 0.2, "location": [0, 0, 2], "object_name": "hoja_espada", "parameters": {{"scale": [0.2, 1, 4]}}}},
     {{"command": "set_material_color", "object_name": "hoja_espada", "color": [0.5, 0.8, 1.0, 0.9]}},
     {{"command": "add_modifier", "object_name": "hoja_espada", "modifier_type": "bevel", "parameters": {{"width": 0.02, "segments": 3}}}},
     {{"command": "add_primitive", "type": "cylinder", "size": 0.15, "location": [0, 0, 0], "object_name": "empunadura", "parameters": {{"scale": [1, 1, 1.5]}}}},
     {{"command": "set_material_color", "object_name": "empunadura", "color": [0.8, 0.8, 0.8, 1]}},
     {{"command": "add_primitive", "type": "cube", "size": 0.15, "location": [0, 0, 0.8], "object_name": "guardamano", "parameters": {{"scale": [1.5, 0.2, 0.2]}}}},
     {{"command": "set_material_color", "object_name": "guardamano", "color": [0.8, 0.8, 0.8, 1]}},
     {{"command": "add_primitive", "type": "sphere", "size": 0.3, "location": [0, 0, -0.5], "object_name": "pomo", "parameters": {{}}}},
     {{"command": "set_material_color", "object_name": "pomo", "color": [0.5, 0.8, 1.0, 0.9]}}
   ]

2. Prompt: "haz una casa de madera"
   Respuesta: [
     {{"command": "add_primitive", "type": "cube", "size": 2, "location": [0, 0, 1], "object_name": "paredes", "parameters": {{"scale": [2, 2, 2]}}}},
     {{"command": "set_material_color", "object_name": "paredes", "color": [0.8, 0.6, 0.4, 1]}},
     {{"command": "add_primitive", "type": "cone", "size": 1.5, "location": [0, 0, 3], "object_name": "tejado", "parameters": {{"scale": [2, 2, 1]}}}},
     {{"command": "set_material_color", "object_name": "tejado", "color": [0.6, 0.3, 0.2, 1]}},
     {{"command": "add_primitive", "type": "cube", "size": 0.5, "location": [0.8, 0, 1], "object_name": "puerta", "parameters": {{"scale": [0.4, 0.1, 1.8]}}}},
     {{"command": "set_material_color", "object_name": "puerta", "color": [0.4, 0.2, 0.1, 1]}},
     {{"command": "add_primitive", "type": "cube", "size": 0.3, "location": [0, 0.8, 1.5], "object_name": "ventana", "parameters": {{"scale": [0.6, 0.1, 0.6]}}}},
     {{"command": "set_material_color", "object_name": "ventana", "color": [0.9, 0.9, 1.0, 0.7]}}
   ]

Comandos permitidos y su formato:
1. Crear primitiva:
   {{"command": "add_primitive", "type": "cube|sphere|cone|cylinder|plane|torus|monkey|torusknot|grid|circle|curve|text", "size": <float>, "location": [<x>, <y>, <z>], "object_name": "<nombre_opcional>", "parameters": {{"param1": "value1", "param2": "value2"}}}}
   - 'type': Tipo de objeto (solo los listados).
   - 'size': Tamano general (diametro para esfera/cilindro/cono, lado para cubo/plano). Default: 1.0.
   - 'location': Coordenadas [x, y, z] donde crear el objeto. Default: [0, 0, 0].
   - 'object_name': (Opcional) Un nombre unico para referenciar este objeto despues.
   - 'parameters': (Opcional) Parametros especificos para cada tipo de objeto.

2. Establecer color de material:
   {{"command": "set_material_color", "object_name": "<nombre_objeto>", "color": [<r>, <g>, <b>, <a>]}}
   - 'color': Lista de 4 floats [R, G, B, Alpha] entre 0.0 y 1.0. Default: [1, 1, 1, 1].

3. Mover objeto:
   {{"command": "move_object", "object_name": "<nombre_objeto>", "location": [<x>, <y>, <z>]}}

4. Escalar objeto:
   {{"command": "scale_object", "object_name": "<nombre_objeto>", "scale": [<sx>, <sy>, <sz>]}}

5. Rotar objeto:
   {{"command": "rotate_object", "object_name": "<nombre_objeto>", "rotation": [<rx>, <ry>, <rz>]}}

6. Aplicar modificador:
   {{"command": "add_modifier", "object_name": "<nombre_objeto>", "modifier_type": "subsurf|bevel|mirror|boolean|array|solidify|wireframe|displace|decimate|remesh|skin|smooth|simple_deform|mesh_deform|cast|wave|build|mask|explode|fluid", "parameters": {{"param1": "value1", "param2": "value2"}}}}

7. Crear objeto desde curva:
   {{"command": "create_from_curve", "curve_type": "bezier|nurbs|poly", "points": [[<x1>, <y1>, <z1>], [<x2>, <y2>, <z2>], ...], "object_name": "<nombre_opcional>"}}

8. Crear objeto desde vertices:
   {{"command": "create_from_vertices", "vertices": [[<x1>, <y1>, <z1>], ...], "faces": [[<v1>, <v2>, <v3>], ...], "object_name": "<nombre_opcional>"}}

9. Unir objetos:
   {{"command": "join_objects", "object_names": ["<nombre1>", "<nombre2>", ...]}}

10. Importar objeto:
    {{"command": "import_object", "file_path": "<ruta_archivo>", "object_name": "<nombre_opcional>"}}

Importante: Para 'set_material_color', 'move_object', 'scale_object', 'rotate_object', 'add_modifier', si no proporcionas 'object_name', el comando intentara aplicarse al ultimo objeto creado por 'add_primitive' en esta secuencia.

Prompt del usuario: "{scene.ai_prompt}"

Respuesta JSON:
"""


def construir_prompt_refinar():
    return """
Eres un asistente que modifica listas JSON de comandos para Blender.
Recibiras la lista JSON actual de comandos y una instruccion del usuario para modificar o mejorar el objeto generado.
Debes responder SOLO con la lista JSON completa y actualizada, siguiendo exactamente el mismo esquema de comandos.
No anadas explicaciones, comentarios ni marcadores ```json```. Si la instruccion no se puede cumplir, devuelve la misma lista.

Comandos permitidos y su formato:
1. Crear primitiva:
   {"command": "add_primitive", "type": "cube|sphere|cone|cylinder|plane|torus|monkey|torusknot|grid|circle|curve|text", "size": <float>, "location": [<x>, <y>, <z>], "object_name": "<nombre_opcional>", "parameters": {"param1": "value1"}}
2. Establecer color de material:
   {"command": "set_material_color", "object_name": "<nombre_objeto>", "color": [<r>, <g>, <b>, <a>]}
3. Mover objeto:
   {"command": "move_object", "object_name": "<nombre_objeto>", "location": [<x>, <y>, <z>]}
4. Escalar objeto:
   {"command": "scale_object", "object_name": "<nombre_objeto>", "scale": [<sx>, <sy>, <sz>]}
5. Rotar objeto:
   {"command": "rotate_object", "object_name": "<nombre_objeto>", "rotation": [<rx>, <ry>, <rz>]}
6. Aplicar modificador:
   {"command": "add_modifier", "object_name": "<nombre_objeto>", "modifier_type": "subsurf|bevel|mirror|boolean|array|solidify|wireframe|displace|decimate|remesh|skin|smooth|simple_deform|mesh_deform|cast|wave|build|mask|explode|fluid", "parameters": {"param1": "value1"}}
7. Crear objeto desde curva:
   {"command": "create_from_curve", "curve_type": "bezier|nurbs|poly", "points": [[<x1>, <y1>, <z1>], [<x2>, <y2>, <z2>], ...], "object_name": "<nombre_opcional>"}
8. Crear objeto desde vertices:
   {"command": "create_from_vertices", "vertices": [[<x1>, <y1>, <z1>], ...], "faces": [[<v1>, <v2>, <v3>], ...], "object_name": "<nombre_opcional>"}
9. Unir objetos:
   {"command": "join_objects", "object_names": ["<nombre1>", "<nombre2>", ...]}
10. Importar objeto:
    {"command": "import_object", "file_path": "<ruta_archivo>", "object_name": "<nombre_opcional>"}
"""


def sync_text(scene):
    text_block = scene.ai_commands_text
    if text_block is None:
        text_block = bpy.data.texts.get("AI_Comandos")
        if text_block is None:
            text_block = bpy.data.texts.new("AI_Comandos")
        scene.ai_commands_text = text_block
    text_block.clear()
    text_block.write(scene.ai_commands_json)


def add_history(scene, prompt, json_text, provider, status):
    while len(scene.ai_history) >= 30:
        scene.ai_history.remove(0)
    item = scene.ai_history.add()
    item.prompt = prompt
    item.json_text = json_text
    item.provider = provider
    item.status = status
    item.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    scene.ai_history_index = len(scene.ai_history) - 1


def ejecutar_lista_comandos(context, comandos, report=None):
    ultimo_objeto_creado_nombre = None

    for i, cmd_data in enumerate(comandos):
        if not isinstance(cmd_data, dict) or "command" not in cmd_data:
            print(f"Item {i} invalido en la lista JSON (omitido): {cmd_data}")
            continue

        comando = cmd_data.get("command", "unknown")
        print(f"Ejecutando comando {i+1}: {comando}")

        try:
            if comando == "add_primitive":
                tipo = cmd_data.get("type", "cube").lower()
                size = float(cmd_data.get("size", 1.0))
                location = cmd_data.get("location", [0.0, 0.0, 0.0])
                obj_name_ai = cmd_data.get("object_name")
                parameters = cmd_data.get("parameters", {}) or {}

                if tipo not in ["cube", "sphere", "cone", "cylinder", "plane", "torus", "monkey", "torusknot", "grid", "circle", "curve", "text"]:
                    print(f"  Error: Tipo de primitiva desconocido '{tipo}'. Omitiendo.")
                    continue
                if not isinstance(location, list) or len(location) != 3:
                    print(f"  Error: 'location' invalida: {location}. Usando [0,0,0].")
                    location = [0.0, 0.0, 0.0]
                try:
                    location = tuple(float(c) for c in location)
                except (ValueError, TypeError):
                    print(f"  Error: Coordenadas de 'location' no numericas: {location}. Usando [0,0,0].")
                    location = (0.0, 0.0, 0.0)

                if tipo == "cube":
                    bpy.ops.mesh.primitive_cube_add(size=size, location=location)
                elif tipo == "sphere":
                    bpy.ops.mesh.primitive_uv_sphere_add(radius=size / 2.0, location=location)
                elif tipo == "cone":
                    bpy.ops.mesh.primitive_cone_add(radius1=size / 2.0, depth=size, location=location)
                elif tipo == "cylinder":
                    bpy.ops.mesh.primitive_cylinder_add(radius=size / 2.0, depth=size, location=location)
                elif tipo == "plane":
                    bpy.ops.mesh.primitive_plane_add(size=size, location=location)
                elif tipo == "torus":
                    bpy.ops.mesh.primitive_torus_add(major_radius=size / 2.0, minor_radius=size / 4.0, location=location)
                elif tipo == "monkey":
                    bpy.ops.mesh.primitive_monkey_add(size=size, location=location)
                elif tipo == "torusknot":
                    bpy.ops.mesh.primitive_torusknot_add(major_radius=size / 2.0, minor_radius=size / 4.0, location=location)
                elif tipo == "grid":
                    subdivisions = int(parameters.get("subdivisions", 10))
                    bpy.ops.mesh.primitive_grid_add(size=size, x_subdivisions=subdivisions, y_subdivisions=subdivisions, location=location)
                elif tipo == "circle":
                    bpy.ops.mesh.primitive_circle_add(radius=size / 2.0, location=location)
                elif tipo == "curve":
                    bpy.ops.curve.primitive_bezier_circle_add(radius=size / 2.0, location=location)
                elif tipo == "text":
                    text_content = parameters.get("text", "Text")
                    bpy.ops.object.text_add(location=location)
                    context.active_object.data.body = text_content
                    context.active_object.data.size = size

                current_object = context.active_object
                if current_object:
                    if obj_name_ai and isinstance(obj_name_ai, str) and obj_name_ai.strip():
                        current_object.name = obj_name_ai.strip()
                    else:
                        base_name = f"AI_{tipo.capitalize()}"
                        count = 1
                        new_name = base_name
                        while new_name in bpy.data.objects:
                            new_name = f"{base_name}.{count:03d}"
                            count += 1
                        current_object.name = new_name
                    ultimo_objeto_creado_nombre = current_object.name
                    print(f"  Creado '{current_object.name}' de tipo '{tipo}' en {location}")
                else:
                    print(f"  Error: No se pudo obtener referencia al objeto creado de tipo '{tipo}'")

            elif comando in ["set_material_color", "move_object", "scale_object"]:
                obj_name = cmd_data.get("object_name", ultimo_objeto_creado_nombre)

                if not obj_name:
                    print(f"  Error en comando '{comando}': No se especifico 'object_name' y no hay objeto previo creado. Omitiendo.")
                    continue
                if obj_name not in bpy.data.objects:
                    print(f"  Error en comando '{comando}': Objeto '{obj_name}' no encontrado en la escena. Omitiendo.")
                    continue

                target_obj = bpy.data.objects[obj_name]

                if comando == "set_material_color":
                    color_rgba = cmd_data.get("color", [1.0, 1.0, 1.0, 1.0])
                    if not isinstance(color_rgba, list) or len(color_rgba) != 4:
                        print(f"  Error: 'color' invalido: {color_rgba}. Usando blanco.")
                        color_rgba = [1.0, 1.0, 1.0, 1.0]
                    try:
                        color_rgba = tuple(max(0.0, min(1.0, float(c))) for c in color_rgba)
                    except (ValueError, TypeError):
                        print(f"  Error: Componentes de 'color' no numericos: {color_rgba}. Usando blanco.")
                        color_rgba = (1.0, 1.0, 1.0, 1.0)

                    if not target_obj.data.materials:
                        mat_name = f"{target_obj.name}_Material"
                        mat = bpy.data.materials.get(mat_name)
                        if not mat:
                            mat = bpy.data.materials.new(name=mat_name)
                        target_obj.data.materials.append(mat)
                        mat.use_nodes = True
                    else:
                        mat = target_obj.data.materials[0]
                        if not mat.use_nodes:
                            mat.use_nodes = True

                    if mat.node_tree and mat.node_tree.nodes:
                        principled_bsdf = None
                        for node in mat.node_tree.nodes:
                            if node.type == 'BSDF_PRINCIPLED':
                                principled_bsdf = node
                                break
                        if not principled_bsdf:
                            principled_bsdf = mat.node_tree.nodes.new('ShaderNodeBsdfPrincipled')
                            output_node = mat.node_tree.nodes.get('Material Output')
                            if output_node:
                                mat.node_tree.links.new(principled_bsdf.outputs['BSDF'], output_node.inputs['Surface'])
                        if principled_bsdf:
                            principled_bsdf.inputs["Base Color"].default_value = color_rgba
                            print(f"  Aplicado color {color_rgba} a material de '{obj_name}'")
                        else:
                            print(f"  Error: No se pudo encontrar o crear nodo BSDF_PRINCIPLED para material de '{obj_name}'")
                    else:
                        print(f"  Error: El material de '{obj_name}' no tiene un arbol de nodos valido.")

                elif comando == "move_object":
                    location = cmd_data.get("location", [0.0, 0.0, 0.0])
                    if not isinstance(location, list) or len(location) != 3:
                        print(f"  Error: 'location' invalida para mover: {location}. Omitiendo.")
                        continue
                    try:
                        location = tuple(float(c) for c in location)
                    except (ValueError, TypeError):
                        print(f"  Error: Coordenadas de 'location' no numericas: {location}. Omitiendo.")
                        continue
                    target_obj.location = location
                    print(f"  Movido '{obj_name}' a {location}")

                elif comando == "scale_object":
                    scale = cmd_data.get("scale", [1.0, 1.0, 1.0])
                    if not isinstance(scale, list) or len(scale) != 3:
                        print(f"  Error: 'scale' invalido para escalar: {scale}. Omitiendo.")
                        continue
                    try:
                        scale = tuple(float(s) for s in scale)
                    except (ValueError, TypeError):
                        print(f"  Error: Componentes de 'scale' no numericos: {scale}. Omitiendo.")
                        continue
                    target_obj.scale = scale
                    print(f"  Escalado '{obj_name}' a {scale}")

            elif comando == "rotate_object":
                obj_name = cmd_data.get("object_name", ultimo_objeto_creado_nombre)

                if not obj_name:
                    print(f"  Error en comando '{comando}': No se especifico 'object_name' y no hay objeto previo creado. Omitiendo.")
                    continue
                if obj_name not in bpy.data.objects:
                    print(f"  Error en comando '{comando}': Objeto '{obj_name}' no encontrado en la escena. Omitiendo.")
                    continue

                target_obj = bpy.data.objects[obj_name]
                rotation = cmd_data.get("rotation", [0.0, 0.0, 0.0])

                if not isinstance(rotation, list) or len(rotation) != 3:
                    print(f"  Error: 'rotation' invalida: {rotation}. Omitiendo.")
                    continue
                try:
                    rotation = tuple(float(r) for r in rotation)
                except (ValueError, TypeError):
                    print(f"  Error: Angulos de 'rotation' no numericos: {rotation}. Omitiendo.")
                    continue

                target_obj.rotation_euler = rotation
                print(f"  Rotado '{obj_name}' a {rotation}")

            elif comando == "add_modifier":
                obj_name = cmd_data.get("object_name", ultimo_objeto_creado_nombre)
                modifier_type = cmd_data.get("modifier_type", "")
                parameters = cmd_data.get("parameters", {}) or {}

                if not obj_name:
                    print(f"  Error en comando '{comando}': No se especifico 'object_name' y no hay objeto previo creado. Omitiendo.")
                    continue
                if obj_name not in bpy.data.objects:
                    print(f"  Error en comando '{comando}': Objeto '{obj_name}' no encontrado en la escena. Omitiendo.")
                    continue
                if not modifier_type:
                    print(f"  Error en comando '{comando}': No se especifico 'modifier_type'. Omitiendo.")
                    continue

                target_obj = bpy.data.objects[obj_name]

                try:
                    modifier = target_obj.modifiers.new(name=f"{modifier_type.capitalize()}", type=modifier_type.upper())

                    if modifier_type == "subsurf":
                        modifier.levels = parameters.get("levels", 1)
                        modifier.render_levels = parameters.get("render_levels", 2)
                    elif modifier_type == "bevel":
                        modifier.width = parameters.get("width", 0.1)
                        modifier.segments = parameters.get("segments", 3)
                    elif modifier_type == "mirror":
                        modifier.use_axis_x = parameters.get("use_axis_x", False)
                        modifier.use_axis_y = parameters.get("use_axis_y", False)
                        modifier.use_axis_z = parameters.get("use_axis_z", False)
                    elif modifier_type == "boolean":
                        target_name = parameters.get("target_object")
                        if target_name and target_name in bpy.data.objects:
                            modifier.object = bpy.data.objects[target_name]
                        else:
                            print(f"  Error: Objeto objetivo '{target_name}' no encontrado para modificador boolean.")
                    elif modifier_type == "array":
                        modifier.count = parameters.get("count", 3)
                        modifier.relative_offset_displace = parameters.get("relative_offset", [1.0, 0.0, 0.0])
                    elif modifier_type == "solidify":
                        modifier.thickness = parameters.get("thickness", 0.1)
                    elif modifier_type == "wireframe":
                        modifier.thickness = parameters.get("thickness", 0.1)
                    elif modifier_type == "displace":
                        modifier.strength = parameters.get("strength", 1.0)
                    elif modifier_type == "decimate":
                        modifier.ratio = parameters.get("ratio", 0.5)
                    elif modifier_type == "remesh":
                        modifier.octree_depth = parameters.get("octree_depth", 4)
                    elif modifier_type == "skin":
                        modifier.branch_smoothing = parameters.get("branch_smoothing", 0.5)
                    elif modifier_type == "smooth":
                        modifier.iterations = parameters.get("iterations", 1)
                    elif modifier_type == "simple_deform":
                        modifier.angle = parameters.get("angle", 45.0)
                        modifier.deform_method = parameters.get("deform_method", "BEND")
                    elif modifier_type == "mesh_deform":
                        target_name = parameters.get("target_object")
                        if target_name and target_name in bpy.data.objects:
                            modifier.object = bpy.data.objects[target_name]
                        else:
                            print(f"  Error: Objeto objetivo '{target_name}' no encontrado para modificador mesh_deform.")
                    elif modifier_type == "cast":
                        modifier.factor = parameters.get("factor", 1.0)
                        modifier.radius = parameters.get("radius", 1.0)
                    elif modifier_type == "wave":
                        modifier.height = parameters.get("height", 1.0)
                        modifier.speed = parameters.get("speed", 1.0)
                    elif modifier_type == "build":
                        modifier.frame_start = parameters.get("frame_start", 1)
                        modifier.frame_duration = parameters.get("frame_duration", 30)
                    elif modifier_type == "mask":
                        modifier.threshold = parameters.get("threshold", 0.5)
                    elif modifier_type == "explode":
                        modifier.particle_uv = parameters.get("particle_uv", 0.0)
                    elif modifier_type == "fluid":
                        modifier.resolution = parameters.get("resolution", 32)

                    print(f"  Aplicado modificador '{modifier_type}' a '{obj_name}'")
                except Exception as e:
                    print(f"  Error aplicando modificador '{modifier_type}' a '{obj_name}': {e}")

            elif comando == "join_objects":
                object_names = cmd_data.get("object_names", [])
                if not object_names or len(object_names) < 2:
                    print(f"  Error en comando '{comando}': Se necesitan al menos dos nombres de objeto. Omitiendo.")
                    continue

                objects_to_join = []
                active_object = None
                for name in object_names:
                    if name in bpy.data.objects:
                        obj = bpy.data.objects[name]
                        if obj.type == 'MESH':
                            objects_to_join.append(obj)
                            if active_object is None:
                                active_object = obj
                        else:
                            print(f"  Advertencia: El objeto '{name}' no es de tipo MESH y no sera unido.")
                    else:
                        print(f"  Error en comando '{comando}': Objeto '{name}' no encontrado. Omitiendo union.")
                        objects_to_join = []
                        break

                if len(objects_to_join) >= 2 and active_object:
                    bpy.ops.object.select_all(action='DESELECT')
                    for obj in objects_to_join:
                        obj.select_set(True)
                    context.view_layer.objects.active = active_object
                    try:
                        bpy.ops.object.join()
                        ultimo_objeto_creado_nombre = active_object.name
                        print(f"  Objetos {object_names} unidos en '{active_object.name}'")
                    except Exception as e:
                        print(f"  Error durante bpy.ops.object.join(): {e}")
                elif len(objects_to_join) < 2:
                    print(f"  Error en comando '{comando}': No hay suficientes objetos validos para unir.")

            elif comando == "create_from_curve":
                curve_type = cmd_data.get("curve_type", "bezier")
                points = cmd_data.get("points", [])
                obj_name = cmd_data.get("object_name")

                if not points or len(points) < 2:
                    print(f"  Error: Se necesitan al menos 2 puntos para crear una curva. Omitiendo.")
                    continue

                try:
                    name = obj_name if obj_name else f"Curve_AI_{len(bpy.data.objects)}"
                    curve = bpy.data.curves.new(name=f"Curve_{name}", type='CURVE')
                    curve.dimensions = '3D'
                    curve.resolution_u = 12
                    curve.bevel_depth = 0.0
                    curve.bevel_resolution = 0

                    polyline = curve.splines.new('POLY')
                    polyline.points.add(len(points) - 1)
                    for i, point in enumerate(points):
                        if i < len(polyline.points):
                            polyline.points[i].co = (point[0], point[1], point[2], 1.0)

                    curve_obj = bpy.data.objects.new(name, curve)
                    context.scene.collection.objects.link(curve_obj)

                    if curve_type == "bezier":
                        for spline in curve_obj.data.splines:
                            spline.type = 'BEZIER'
                            for p in spline.bezier_points:
                                p.handle_type = 'AUTO'
                    elif curve_type == "nurbs":
                        for spline in curve_obj.data.splines:
                            spline.type = 'NURBS'

                    ultimo_objeto_creado_nombre = curve_obj.name
                    print(f"  Creada curva {curve_type} '{curve_obj.name}' con {len(points)} puntos")
                except Exception as e:
                    print(f"  Error creando curva: {e}")

            elif comando == "create_from_vertices":
                vertices = cmd_data.get("vertices", [])
                faces = cmd_data.get("faces", [])
                obj_name = cmd_data.get("object_name")

                if not vertices:
                    print(f"  Error: Se necesitan vertices para crear un objeto. Omitiendo.")
                    continue

                try:
                    name = obj_name if obj_name else f"Mesh_AI_{len(bpy.data.objects)}"
                    mesh = bpy.data.meshes.new(name=f"Mesh_{name}")
                    obj = bpy.data.objects.new(name, mesh)
                    context.scene.collection.objects.link(obj)

                    mesh.from_pydata(vertices, [], faces)
                    mesh.update()

                    ultimo_objeto_creado_nombre = obj.name
                    print(f"  Creado objeto desde vertices '{obj.name}' con {len(vertices)} vertices y {len(faces)} caras")
                except Exception as e:
                    print(f"  Error creando objeto desde vertices: {e}")

            elif comando == "import_object":
                file_path = cmd_data.get("file_path", "")
                obj_name = cmd_data.get("object_name")

                if not file_path:
                    print(f"  Error: Se necesita una ruta de archivo para importar. Omitiendo.")
                    continue

                try:
                    file_ext = os.path.splitext(file_path)[1].lower()

                    if file_ext == '.obj':
                        bpy.ops.import_scene.obj(filepath=file_path)
                    elif file_ext == '.fbx':
                        bpy.ops.import_scene.fbx(filepath=file_path)
                    elif file_ext in ['.glb', '.gltf']:
                        bpy.ops.import_scene.gltf(filepath=file_path)
                    elif file_ext == '.stl':
                        bpy.ops.import_mesh.stl(filepath=file_path)
                    else:
                        print(f"  Error: Formato de archivo no soportado '{file_ext}'. Omitiendo.")
                        continue

                    if context.selected_objects:
                        imported = context.selected_objects[0]
                        if obj_name:
                            imported.name = obj_name
                        ultimo_objeto_creado_nombre = imported.name
                        print(f"  Importado objeto '{ultimo_objeto_creado_nombre}' desde '{file_path}'")
                except Exception as e:
                    print(f"  Error importando objeto desde '{file_path}': {e}")

            else:
                print(f"  Comando desconocido recibido y omitido: {comando}")

        except Exception as e:
            import traceback
            print(f"!! Error inesperado ejecutando comando {i+1} ({comando}): {e}")
            print(traceback.format_exc())
            if report:
                report({'ERROR'}, f"Error ejecutando comando {comando}: {e}")

    return {'FINISHED'}


def ejecutar_desde_escena(context, report):
    scene = context.scene
    if scene.ai_commands_text is not None:
        scene.ai_commands_json = scene.ai_commands_text.as_string()

    raw = scene.ai_commands_json.strip()
    if not raw:
        report({'ERROR'}, "No hay comandos para ejecutar. Genera comandos primero.")
        return {'CANCELLED'}

    try:
        comandos = json.loads(raw)
    except json.JSONDecodeError as e:
        report({'ERROR'}, f"El JSON tiene errores: {e}")
        return {'CANCELLED'}

    if not isinstance(comandos, list):
        report({'ERROR'}, "El JSON debe ser una lista de comandos.")
        return {'CANCELLED'}

    if not comandos:
        report({'WARNING'}, "La lista de comandos esta vacia.")
        return {'FINISHED'}

    resultado = ejecutar_lista_comandos(context, comandos, report)
    add_history(scene, scene.ai_prompt, scene.ai_commands_json, scene.ai_provider, "ejecutado")
    return resultado


# --- Servidor TCP para la ventana externa (tkinter) ---
_server_thread = None
_server_socket = None
_timer_handle = None
_stop_event = None
_pending = queue.Queue()
_responses = queue.Queue()


def _resp(rid, ok, data=None, error=None, messages=None):
    r = {"id": rid, "ok": bool(ok), "data": data if data is not None else {}, "messages": messages or []}
    if error:
        r["error"] = error
    return r


def _hacer_report(mensajes):
    def _r(tipo, msg):
        mensajes.append(f"{tipo[0]}: {msg}")
        print(f"[Generador AI Servidor] {tipo[0]}: {msg}")
    return _r


def _procesar_peticion(req, context):
    scene = context.scene
    rid = req.get("id", 0)
    accion = req.get("action", "ping")

    try:
        if accion == "ping":
            return _resp(rid, True, data={
                "message": "pong",
                "blender": bpy.app.version_string,
                "addon": ".".join(str(v) for v in bl_info["version"]),
            })

        if accion == "get_state":
            return _resp(rid, True, data={
                "provider": scene.ai_provider,
                "ai_prompt": scene.ai_prompt,
                "ai_commands_json": scene.ai_commands_json,
                "ai_status": scene.ai_status,
                "version": {"blender": bpy.app.version_string,
                            "addon": ".".join(str(v) for v in bl_info["version"])},
                "providers": {
                    pid: {"label": cls.label, "available": cls.available()}
                    for pid, cls in PROVIDERS.items()
                },
                "history": [
                    {"prompt": h.prompt, "json_text": h.json_text, "provider": h.provider,
                     "status": h.status, "timestamp": h.timestamp}
                    for h in scene.ai_history
                ],
            })

        if accion == "generate":
            mensajes = []
            report = _hacer_report(mensajes)
            prompt = str(req.get("prompt", "")).strip()
            if not prompt:
                return _resp(rid, False, error="El prompt esta vacio.", messages=mensajes)
            provider = req.get("provider", scene.ai_provider)
            if provider not in PROVIDERS:
                return _resp(rid, False, error=f"Proveedor desconocido: {provider}", messages=mensajes)

            prev = (scene.use_composition, scene.composition_type, scene.composition_style)
            scene.use_composition = bool(req.get("use_composition", False))
            scene.composition_type = str(req.get("composition_type", "CUSTOM"))
            scene.composition_style = str(req.get("composition_style", "REALISTIC"))
            try:
                system_prompt = construir_prompt_sistema(scene)
            finally:
                scene.use_composition, scene.composition_type, scene.composition_style = prev

            resultado = generar_texto(context, system_prompt, prompt, provider, report)
            if resultado is None:
                return _resp(rid, False, error="Fallaron todos los proveedores.", messages=mensajes)

            provider_id, texto = resultado
            limpio = limpiar_json(texto)
            try:
                comandos = json.loads(limpio)
            except json.JSONDecodeError as e:
                return _resp(rid, False, error=f"El proveedor devolvio JSON invalido: {e}", messages=mensajes)
            if not isinstance(comandos, list):
                return _resp(rid, False, error="La respuesta del proveedor no es una lista de comandos.", messages=mensajes)

            scene.ai_commands_json = json.dumps(comandos, ensure_ascii=False, indent=2)
            sync_text(scene)
            scene.ai_status = f"Generado con {PROVIDERS[provider_id].label}: {len(comandos)} comandos."
            add_history(scene, prompt, scene.ai_commands_json, provider_id, "generado")

            datos = {
                "commands_json": scene.ai_commands_json,
                "count": len(comandos),
                "provider_used": provider_id,
                "status": scene.ai_status,
                "executed": False,
            }
            if req.get("auto_execute", False) and comandos:
                ejecutar_desde_escena(context, report)
                datos["executed"] = True
            return _resp(rid, True, data=datos, messages=mensajes)

        if accion == "refine":
            mensajes = []
            report = _hacer_report(mensajes)
            instruccion = str(req.get("instruction", "")).strip()
            commands = req.get("commands_json")
            if commands is not None:
                scene.ai_commands_json = str(commands)
            if scene.ai_commands_text is not None:
                scene.ai_commands_json = scene.ai_commands_text.as_string()
            if not scene.ai_commands_json.strip():
                return _resp(rid, False, error="No hay comandos para refinar.", messages=mensajes)
            if not instruccion:
                return _resp(rid, False, error="La instruccion de refinamiento esta vacia.", messages=mensajes)

            provider = req.get("provider", scene.ai_provider)
            system_prompt = construir_prompt_refinar()
            user_prompt = (
                f"Instruccion del usuario: {instruccion}\n\n"
                f"Comandos JSON actuales:\n{scene.ai_commands_json}"
            )
            resultado = generar_texto(context, system_prompt, user_prompt, provider, report)
            if resultado is None:
                return _resp(rid, False, error="Fallaron todos los proveedores.", messages=mensajes)

            provider_id, texto = resultado
            limpio = limpiar_json(texto)
            try:
                comandos = json.loads(limpio)
            except json.JSONDecodeError as e:
                return _resp(rid, False, error=f"El proveedor devolvio JSON invalido al refinar: {e}", messages=mensajes)
            if not isinstance(comandos, list):
                return _resp(rid, False, error="La respuesta de refinamiento no es una lista de comandos.", messages=mensajes)

            scene.ai_commands_json = json.dumps(comandos, ensure_ascii=False, indent=2)
            sync_text(scene)
            scene.ai_status = f"Refinado con {PROVIDERS[provider_id].label}: {len(comandos)} comandos."
            add_history(scene, f"{scene.ai_prompt} | refinar: {instruccion}", scene.ai_commands_json, provider_id, "refinado")
            return _resp(rid, True, data={
                "commands_json": scene.ai_commands_json,
                "count": len(comandos),
                "provider_used": provider_id,
                "status": scene.ai_status,
            }, messages=mensajes)

        if accion == "execute":
            mensajes = []
            report = _hacer_report(mensajes)
            commands = req.get("commands_json")
            if commands is not None:
                scene.ai_commands_json = str(commands)
            resultado = ejecutar_desde_escena(context, report)
            ok = bool(resultado) and "FINISHED" in resultado
            return _resp(rid, ok, data={"status": scene.ai_status}, messages=mensajes)

        if accion == "preview":
            commands = req.get("commands_json")
            if commands is not None:
                scene.ai_commands_json = str(commands)
            raw = scene.ai_commands_json.strip()
            if not raw:
                return _resp(rid, False, error="No hay comandos para validar.")
            try:
                comandos = json.loads(raw)
            except json.JSONDecodeError as e:
                return _resp(rid, False, error=f"El JSON tiene errores: {e}")
            if not isinstance(comandos, list):
                return _resp(rid, False, error="El JSON debe ser una lista de comandos.")
            tipos = {}
            for c in comandos:
                if isinstance(c, dict):
                    nombre = c.get("command", "desconocido")
                    tipos[nombre] = tipos.get(nombre, 0) + 1
            return _resp(rid, True, data={"count": len(comandos), "summary": tipos})

        if accion == "clear":
            scene.ai_commands_json = ""
            if scene.ai_commands_text is not None:
                scene.ai_commands_text.clear()
            scene.ai_status = ""
            return _resp(rid, True, data={"status": "Comandos borrados."})

        if accion == "clear_history":
            scene.ai_history.clear()
            scene.ai_history_index = -1
            return _resp(rid, True, data={"status": "Historial borrado."})

        return _resp(rid, False, error=f"Accion desconocida: {accion}")

    except Exception as e:
        import traceback
        traceback.print_exc()
        return _resp(rid, False, error=str(e))


def _timer_servidor():
    try:
        while True:
            try:
                req = _pending.get_nowait()
            except queue.Empty:
                break
            try:
                resp = _procesar_peticion(req, bpy.context)
            except Exception as e:
                resp = _resp(req.get("id", 0), False, error=str(e))
            _responses.put(resp)
    except Exception:
        import traceback
        traceback.print_exc()
    return 0.05


class _ServidorTCP(threading.Thread):
    def __init__(self, port, pending, responses, stop_event):
        super().__init__(daemon=True)
        self.port = port
        self.pending = pending
        self.responses = responses
        self.stop_event = stop_event

    def run(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(("127.0.0.1", self.port))
            srv.listen(1)
            srv.settimeout(0.5)
        except OSError as e:
            print(f"[Generador AI Servidor] Error al abrir el puerto {self.port}: {e}")
            return
        global _server_socket
        _server_socket = srv
        print(f"[Generador AI Servidor] Escuchando en 127.0.0.1:{self.port}")
        while not self.stop_event.is_set():
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self._atender_cliente(conn)
            except Exception:
                import traceback
                traceback.print_exc()
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
        try:
            srv.close()
        except OSError:
            pass
        print("[Generador AI Servidor] Servidor detenido.")

    def _atender_cliente(self, conn):
        conn.settimeout(0.5)
        buffer = ""
        while not self.stop_event.is_set():
            try:
                datos = conn.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not datos:
                break
            buffer += datos.decode("utf-8", errors="replace")
            while "\n" in buffer:
                linea, buffer = buffer.split("\n", 1)
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    req = json.loads(linea)
                except json.JSONDecodeError as e:
                    self._enviar(conn, _resp(None, False, error=f"JSON invalido: {e}"))
                    continue
                self.pending.put(req)
                resp = None
                fin = time.time() + 300
                while time.time() < fin:
                    try:
                        candidata = self.responses.get(timeout=1)
                    except queue.Empty:
                        continue
                    if candidata.get("id") == req.get("id"):
                        resp = candidata
                        break
                if resp is None:
                    resp = _resp(req.get("id"), False, error="Tiempo de espera agotado.")
                self._enviar(conn, resp)

    def _enviar(self, conn, resp):
        try:
            conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
        except OSError:
            pass


def _detener_servidor():
    global _server_thread, _server_socket, _timer_handle, _stop_event
    if _timer_handle is not None:
        try:
            bpy.app.timers.unregister(_timer_handle)
        except Exception:
            pass
        _timer_handle = None
    if _stop_event is not None:
        _stop_event.set()
    if _server_thread is not None:
        try:
            _server_thread.join(timeout=2)
        except Exception:
            pass
    _server_thread = None
    _server_socket = None


# --- Ventana externa (tkinter) ---
def _ruta_ventana_cliente():
    import os as _os
    candidatas = []
    try:
        candidatas.append(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "generador_ai_ventana.py"))
    except Exception:
        pass
    for ruta in candidatas:
        if ruta and _os.path.isfile(ruta):
            return ruta
    return None


def _tiene_tkinter(python_exe):
    import subprocess as _sp
    flags = 0
    if sys.platform.startswith("win"):
        flags = 0x08000000
    try:
        r = _sp.run(
            [python_exe, "-c", "import tkinter; print('TK_OK')"],
            capture_output=True, timeout=30, creationflags=flags,
        )
        return r.returncode == 0 and "TK_OK" in r.stdout.decode("utf-8", "replace")
    except Exception:
        return False


def _encontrar_python_tkinter():
    import glob as _glob
    import os as _os
    candidatos = []

    def _agregar(path):
        if path and path not in candidatos:
            candidatos.append(path)

    for var in ("APPDATA", "LOCALAPPDATA"):
        base = _os.environ.get(var)
        if not base:
            continue
        for pat in ("Blender Foundation",):
            raiz = _os.path.join(base, pat)
            for carpeta in _glob.glob(_os.path.join(raiz, "Blender*")):
                nombre = _os.path.basename(carpeta).replace("Blender", "").strip()
                if not nombre or not nombre[0].isdigit():
                    continue
                ver_corta = ".".join(nombre.split(".")[:2])
                python = _os.path.join(carpeta, ver_corta, "python", "bin", "python.exe")
                if not _os.path.isfile(python):
                    python = _os.path.join(carpeta, nombre, "python", "bin", "python.exe")
                _agregar(python)

    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = _os.environ.get(var)
        if not base:
            continue
        for pat in ("Python/*/python.exe", "Python*/python.exe"):
            for p in _glob.glob(_os.path.join(base, pat)):
                _agregar(p)

    if sys.platform.startswith("win"):
        for cmd in ("py", "python", "pythonw"):
            _agregar(cmd)
    else:
        for cmd in ("python3", "python"):
            _agregar(cmd)

    for c in candidatos:
        if _tiene_tkinter(c):
            return c
    return None


# --- Operadores ---
class OBJECT_OT_ai_generar_comandos(bpy.types.Operator):
    bl_idname = "object.ai_generar_comandos"
    bl_label = "Generar Comandos AI"
    bl_description = "Genera comandos JSON desde el prompt usando el proveedor seleccionado"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        prompt = scene.ai_prompt.strip()
        if not prompt:
            self.report({'ERROR'}, "Escribe un prompt primero.")
            return {'CANCELLED'}

        system_prompt = construir_prompt_sistema(scene)
        resultado = generar_texto(context, system_prompt, prompt, scene.ai_provider, self.report)
        if resultado is None:
            return {'CANCELLED'}

        provider_id, texto = resultado
        limpio = limpiar_json(texto)
        try:
            comandos = json.loads(limpio)
        except json.JSONDecodeError as e:
            self.report({'ERROR'}, f"El proveedor devolvio un JSON invalido: {e}")
            print(f"Respuesta del proveedor:\n>>>\n{limpio}\n<<<")
            return {'CANCELLED'}

        if not isinstance(comandos, list):
            self.report({'ERROR'}, "La respuesta del proveedor no es una lista de comandos.")
            return {'CANCELLED'}

        scene.ai_commands_json = json.dumps(comandos, ensure_ascii=False, indent=2)
        sync_text(scene)
        scene.ai_status = f"Generado con {PROVIDERS[provider_id].label}: {len(comandos)} comandos."
        add_history(scene, prompt, scene.ai_commands_json, provider_id, "generado")
        self.report({'INFO'}, f"{len(comandos)} comandos generados. Revisa y pulsa Ejecutar.")

        if scene.ai_auto_execute and comandos:
            return ejecutar_desde_escena(context, self.report)
        return {'FINISHED'}

    def invoke(self, context, event):
        if not context.scene.ai_prompt:
            return context.window_manager.invoke_props_dialog(self)
        return self.execute(context)

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, "ai_provider", text="Proveedor")
        layout.prop(context.scene, "ai_prompt", text="Prompt")


class OBJECT_OT_ai_refinar_comandos(bpy.types.Operator):
    bl_idname = "object.ai_refinar_comandos"
    bl_label = "Refinar Comandos"
    bl_description = "Modifica los comandos generados con una instruccion del usuario"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        if scene.ai_commands_text is not None:
            scene.ai_commands_json = scene.ai_commands_text.as_string()
        if not scene.ai_commands_json.strip():
            self.report({'ERROR'}, "Genera comandos antes de refinar.")
            return {'CANCELLED'}

        instruccion = scene.ai_refine_instruction.strip()
        if not instruccion:
            self.report({'ERROR'}, "Escribe una instruccion de refinamiento.")
            return {'CANCELLED'}

        system_prompt = construir_prompt_refinar()
        user_prompt = (
            f"Instruccion del usuario: {instruccion}\n\n"
            f"Comandos JSON actuales:\n{scene.ai_commands_json}"
        )
        resultado = generar_texto(context, system_prompt, user_prompt, scene.ai_provider, self.report)
        if resultado is None:
            return {'CANCELLED'}

        provider_id, texto = resultado
        limpio = limpiar_json(texto)
        try:
            comandos = json.loads(limpio)
        except json.JSONDecodeError as e:
            self.report({'ERROR'}, f"El proveedor devolvio un JSON invalido al refinar: {e}")
            return {'CANCELLED'}

        if not isinstance(comandos, list):
            self.report({'ERROR'}, "La respuesta de refinamiento no es una lista de comandos.")
            return {'CANCELLED'}

        scene.ai_commands_json = json.dumps(comandos, ensure_ascii=False, indent=2)
        sync_text(scene)
        scene.ai_status = f"Refinado con {PROVIDERS[provider_id].label}: {len(comandos)} comandos."
        add_history(scene, f"{scene.ai_prompt} | refinar: {instruccion}", scene.ai_commands_json, provider_id, "refinado")
        self.report({'INFO'}, f"Comandos refinados: {len(comandos)} comandos.")
        return {'FINISHED'}


class OBJECT_OT_ai_ejecutar_comandos(bpy.types.Operator):
    bl_idname = "object.ai_ejecutar_comandos"
    bl_label = "Ejecutar Comandos"
    bl_description = "Ejecuta los comandos JSON generados en la escena"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return ejecutar_desde_escena(context, self.report)


class OBJECT_OT_ai_previsualizar_comandos(bpy.types.Operator):
    bl_idname = "object.ai_previsualizar_comandos"
    bl_label = "Validar Comandos"
    bl_description = "Valida el JSON y muestra un resumen de los comandos"

    def execute(self, context):
        scene = context.scene
        if scene.ai_commands_text is not None:
            scene.ai_commands_json = scene.ai_commands_text.as_string()

        raw = scene.ai_commands_json.strip()
        if not raw:
            self.report({'ERROR'}, "No hay comandos para validar.")
            return {'CANCELLED'}

        try:
            comandos = json.loads(raw)
        except json.JSONDecodeError as e:
            self.report({'ERROR'}, f"El JSON tiene errores: {e}")
            return {'CANCELLED'}

        if not isinstance(comandos, list):
            self.report({'ERROR'}, "El JSON debe ser una lista de comandos.")
            return {'CANCELLED'}

        tipos = {}
        for c in comandos:
            if isinstance(c, dict):
                nombre = c.get("command", "desconocido")
                tipos[nombre] = tipos.get(nombre, 0) + 1
        resumen = ", ".join(f"{k}: {v}" for k, v in tipos.items()) or "vacia"
        self.report({'INFO'}, f"{len(comandos)} comandos. {resumen}")
        print(f"Resumen de comandos validados:\n{resumen}")
        return {'FINISHED'}


class OBJECT_OT_ai_limpiar_comandos(bpy.types.Operator):
    bl_idname = "object.ai_limpiar_comandos"
    bl_label = "Limpiar Comandos"
    bl_description = "Borra los comandos generados"

    def execute(self, context):
        scene = context.scene
        scene.ai_commands_json = ""
        if scene.ai_commands_text is not None:
            scene.ai_commands_text.clear()
        scene.ai_status = ""
        self.report({'INFO'}, "Comandos borrados.")
        return {'FINISHED'}


class OBJECT_OT_ai_crear_texto(bpy.types.Operator):
    bl_idname = "object.ai_crear_texto"
    bl_label = "Nuevo Texto"
    bl_description = "Crea un bloque de texto para editar los comandos JSON"

    def execute(self, context):
        scene = context.scene
        if scene.ai_commands_text is None:
            text_block = bpy.data.texts.get("AI_Comandos")
            if text_block is None:
                text_block = bpy.data.texts.new("AI_Comandos")
            scene.ai_commands_text = text_block
        if not scene.ai_commands_json.strip():
            scene.ai_commands_json = "[]"
        sync_text(scene)
        return {'FINISHED'}


class OBJECT_OT_ai_abrir_editor(bpy.types.Operator):
    bl_idname = "object.ai_abrir_editor"
    bl_label = "Abrir en Editor de Texto"
    bl_description = "Abre el bloque de comandos en el editor de texto de Blender"

    def execute(self, context):
        scene = context.scene
        if scene.ai_commands_text is None:
            self.report({'ERROR'}, "Primero crea o genera un bloque de comandos.")
            return {'CANCELLED'}
        encontrado = False
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'TEXT_EDITOR':
                    area.spaces.active.text = scene.ai_commands_text
                    encontrado = True
        if not encontrado:
            self.report({'WARNING'}, "No hay ninguna ventana de Editor de Texto abierta.")
        else:
            self.report({'INFO'}, "Bloque abierto en el Editor de Texto.")
        return {'FINISHED'}


class OBJECT_OT_ai_history_use(bpy.types.Operator):
    bl_idname = "object.ai_history_use"
    bl_label = "Cargar del Historial"
    bl_description = "Carga el prompt y los comandos seleccionados"

    def execute(self, context):
        scene = context.scene
        if scene.ai_history_index < 0 or scene.ai_history_index >= len(scene.ai_history):
            return {'CANCELLED'}
        item = scene.ai_history[scene.ai_history_index]
        scene.ai_prompt = item.prompt
        scene.ai_commands_json = item.json_text
        if item.provider in PROVIDERS:
            scene.ai_provider = item.provider
        sync_text(scene)
        self.report({'INFO'}, "Prompt y comandos cargados del historial.")
        return {'FINISHED'}


class OBJECT_OT_ai_history_del(bpy.types.Operator):
    bl_idname = "object.ai_history_del"
    bl_label = "Eliminar del Historial"

    def execute(self, context):
        scene = context.scene
        if scene.ai_history_index >= 0 and scene.ai_history_index < len(scene.ai_history):
            scene.ai_history.remove(scene.ai_history_index)
            scene.ai_history_index = min(scene.ai_history_index, len(scene.ai_history) - 1)
        return {'FINISHED'}


class OBJECT_OT_ai_history_clear(bpy.types.Operator):
    bl_idname = "object.ai_history_clear"
    bl_label = "Vaciar Historial"

    def execute(self, context):
        context.scene.ai_history.clear()
        context.scene.ai_history_index = -1
        return {'FINISHED'}


class OBJECT_OT_ai_server_start(bpy.types.Operator):
    bl_idname = "object.ai_server_start"
    bl_label = "Iniciar Servidor"
    bl_description = "Inicia el servidor TCP para conectar la ventana externa (tkinter)"
    bl_options = {'REGISTER'}

    def execute(self, context):
        global _server_thread, _timer_handle, _stop_event, _pending, _responses
        if _server_thread is not None and _server_thread.is_alive():
            self.report({'WARNING'}, "El servidor ya esta en marcha.")
            return {'CANCELLED'}

        prefs = context.preferences.addons[__name__].preferences
        port = int(prefs.server_port)

        _pending = queue.Queue()
        _responses = queue.Queue()
        _stop_event = threading.Event()
        _server_thread = _ServidorTCP(port, _pending, _responses, _stop_event)
        _server_thread.start()
        _timer_handle = bpy.app.timers.register(_timer_servidor, first_interval=0.05)

        context.scene.ai_server_status = f"Servidor activo en 127.0.0.1:{port}"
        self.report({'INFO'}, f"Servidor iniciado en el puerto {port}. Conecta la ventana externa.")
        return {'FINISHED'}


class OBJECT_OT_ai_server_stop(bpy.types.Operator):
    bl_idname = "object.ai_server_stop"
    bl_label = "Detener Servidor"
    bl_description = "Detiene el servidor TCP"

    def execute(self, context):
        _detener_servidor()
        context.scene.ai_server_status = "Servidor detenido."
        self.report({'INFO'}, "Servidor detenido.")
        return {'FINISHED'}


class OBJECT_OT_ai_abrir_ventana_cliente(bpy.types.Operator):
    bl_idname = "object.ai_abrir_ventana_cliente"
    bl_label = "Abrir Ventana Cliente"
    bl_description = "Lanza 'generador_ai_ventana.py' (cliente tkinter) usando un Python del sistema con tkinter"
    bl_options = {'REGISTER'}

    def execute(self, context):
        ruta = _ruta_ventana_cliente()
        if ruta is None:
            self.report({'ERROR'}, "No se encontro 'generador_ai_ventana.py' junto a este addon.")
            return {'CANCELLED'}

        python = _encontrar_python_tkinter()
        if python is None:
            self.report({'ERROR'}, "No se encontro un Python del sistema con tkinter disponible.")
            return {'CANCELLED'}

        flags = 0
        if sys.platform.startswith("win"):
            flags = 0x08000000
        try:
            subprocess.Popen(
                [python, ruta],
                creationflags=flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            self.report({'ERROR'}, f"No se pudo lanzar la ventana cliente: {e}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Ventana cliente abierta con: {python}")
        return {'FINISHED'}


# --- UIList del historial ---
class AI_UL_historial(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.label(text=f"{item.status}: {item.prompt[:40]}", icon='FILE_TEXT')
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'


# --- Panel en la UI ---
class OBJECT_PT_generador_ai_panel(bpy.types.Panel):
    bl_label = "Generador AI"
    bl_idname = "OBJECT_PT_generador_ai"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Generador AI"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        prefs = context.preferences.addons[__name__].preferences

        box = layout.box()
        box.label(text="Proveedor AI:", icon='WORLD_DATA')
        box.prop(scene, "ai_provider", text="")
        cls = PROVIDERS.get(scene.ai_provider)
        if cls is not None:
            if not cls.available():
                box.label(text=f"Falta la libreria '{cls.lib_name}'.", icon='ERROR')
            elif not getattr(prefs, cls.key_prop, "") and not getattr(cls, "no_key_required", False):
                box.label(text="API Key no configurada.", icon='ERROR')
            else:
                box.label(text=f"Modelo: {getattr(prefs, cls.model_prop, '') or cls.model_default}", icon='CHECKMARK')
        box.operator("preferences.addon_show", text="Configurar Proveedores", icon='PREFERENCES').module = __name__

        box = layout.box()
        box.label(text="Prompt:", icon='TEXT')
        box.prop(scene, "ai_prompt", text="")
        row = box.row(align=True)
        row.prop(scene, "use_composition", text="Composicion")
        if scene.use_composition:
            box.prop(scene, "composition_type", text="Tipo")
            box.prop(scene, "composition_style", text="Estilo")
        box.prop(scene, "ai_auto_execute", text="Auto-ejecutar tras generar")
        box.operator("object.ai_generar_comandos", text="Generar Comandos", icon='SHADERFX')

        box = layout.box()
        box.label(text="Comandos (JSON):", icon='FILE_TEXT')
        box.template_ID(scene, "ai_commands_text", new="object.ai_crear_texto")
        if scene.ai_commands_json.strip():
            try:
                comandos = json.loads(scene.ai_commands_json)
                n = len(comandos) if isinstance(comandos, list) else 0
                box.label(text=f"{n} comandos listos para ejecutar.", icon='INFO')
            except json.JSONDecodeError:
                box.label(text="El JSON tiene errores de sintaxis.", icon='ERROR')
        row = box.row(align=True)
        row.operator("object.ai_previsualizar_comandos", text="Validar", icon='CHECKMARK')
        row.operator("object.ai_ejecutar_comandos", text="Ejecutar", icon='PLAY')
        row = box.row(align=True)
        row.operator("object.ai_abrir_editor", text="Editar en Text Editor", icon='TEXT')
        row.operator("object.ai_limpiar_comandos", text="", icon='TRASH')

        box = layout.box()
        box.label(text="Refinar:", icon='GREASEPENCIL')
        box.prop(scene, "ai_refine_instruction", text="")
        box.operator("object.ai_refinar_comandos", text="Refinar Comandos", icon='MODIFIER')

        if scene.ai_status:
            box = layout.box()
            box.label(text=scene.ai_status, icon='INFO')

        box = layout.box()
        box.label(text="Historial:", icon='TIME')
        if len(scene.ai_history) > 0:
            row = box.row()
            row.template_list("AI_UL_historial", "", scene, "ai_history", scene, "ai_history_index", rows=4)
            col = row.column(align=True)
            col.operator("object.ai_history_use", text="", icon='IMPORT')
            col.operator("object.ai_history_del", text="", icon='X')
            col.operator("object.ai_history_clear", text="", icon='TRASH')
        else:
            box.label(text="Sin entradas todavia.", icon='INFO')

        box = layout.box()
        box.label(text="Servidor (ventana externa):", icon='CONSOLE')
        box.prop(prefs, "server_port", text="Puerto")
        row = box.row(align=True)
        row.operator("object.ai_server_start", text="Iniciar Servidor", icon='PLAY')
        row.operator("object.ai_server_stop", text="Detener", icon='PAUSE')
        row = box.row(align=True)
        row.operator("object.ai_abrir_ventana_cliente", text="Abrir Ventana Cliente", icon='WINDOW')
        if scene.ai_server_status:
            box.label(text=scene.ai_server_status, icon='INFO')


# --- Registro ---
classes = (
    GeneradorAIPreferencias,
    HistoriaItem,
    OBJECT_OT_ai_generar_comandos,
    OBJECT_OT_ai_refinar_comandos,
    OBJECT_OT_ai_ejecutar_comandos,
    OBJECT_OT_ai_previsualizar_comandos,
    OBJECT_OT_ai_limpiar_comandos,
    OBJECT_OT_ai_crear_texto,
    OBJECT_OT_ai_abrir_editor,
    OBJECT_OT_ai_history_use,
    OBJECT_OT_ai_history_del,
    OBJECT_OT_ai_history_clear,
    OBJECT_OT_ai_server_start,
    OBJECT_OT_ai_server_stop,
    OBJECT_OT_ai_abrir_ventana_cliente,
    AI_UL_historial,
    OBJECT_PT_generador_ai_panel,
)


def register_scene_props():
    bpy.types.Scene.ai_provider = bpy.props.EnumProperty(
        name="Proveedor AI",
        description="Proveedor de IA a utilizar",
        items=_provider_items,
        default=0,
    )

    bpy.types.Scene.ai_prompt = bpy.props.StringProperty(
        name="Prompt AI",
        description="Describe los objetos que quieres generar con IA",
        default="",
    )

    bpy.types.Scene.ai_commands_json = bpy.props.StringProperty(
        name="Comandos JSON",
        description="Lista JSON de comandos generados o editados",
        default="",
    )

    bpy.types.Scene.ai_commands_text = bpy.props.PointerProperty(
        type=bpy.types.Text,
        name="Comandos (Texto)",
        description="Bloque de texto para editar los comandos JSON",
    )

    bpy.types.Scene.ai_refine_instruction = bpy.props.StringProperty(
        name="Instruccion de refinamiento",
        description="Que quieres modificar, anadir o corregir en los comandos generados",
        default="",
    )

    bpy.types.Scene.ai_auto_execute = bpy.props.BoolProperty(
        name="Auto-ejecutar tras generar",
        description="Ejecuta los comandos automaticamente al generarlos",
        default=False,
    )

    bpy.types.Scene.ai_status = bpy.props.StringProperty(
        name="Estado",
        description="Ultimo mensaje de estado de la generacion",
        default="",
    )

    bpy.types.Scene.use_composition = bpy.props.BoolProperty(
        name="Usar Composicion",
        description="Crear un objeto compuesto por multiples partes",
        default=False,
    )

    bpy.types.Scene.composition_type = bpy.props.EnumProperty(
        name="Tipo de Composicion",
        description="Tipo de objeto compuesto a crear",
        items=[
            ('CHARACTER', "Personaje", "Personaje con cabeza, cuerpo y extremidades"),
            ('VEHICLE', "Vehiculo", "Vehiculo con carroceria, ruedas y detalles"),
            ('BUILDING', "Edificio", "Edificio con estructura, ventanas y detalles"),
            ('FURNITURE', "Mueble", "Mueble con estructura y detalles"),
            ('WEAPON', "Arma", "Arma con mango, hoja y detalles"),
            ('CUSTOM', "Personalizado", "Objeto personalizado definido por el prompt"),
        ],
        default='CUSTOM',
    )

    bpy.types.Scene.composition_style = bpy.props.EnumProperty(
        name="Estilo",
        description="Estilo visual del objeto compuesto",
        items=[
            ('REALISTIC', "Realista", "Estilo realista con detalles y texturas"),
            ('CARTOON', "Cartoon", "Estilo cartoon simplificado"),
            ('LOWPOLY', "Low Poly", "Estilo low poly con pocos poligonos"),
            ('SCIFI', "Ciencia Ficcion", "Estilo futurista o de ciencia ficcion"),
            ('FANTASY', "Fantasia", "Estilo magico o de fantasia"),
        ],
        default='REALISTIC',
    )

    bpy.types.Scene.ai_history = bpy.props.CollectionProperty(type=HistoriaItem)
    bpy.types.Scene.ai_history_index = bpy.props.IntProperty(default=-1)

    bpy.types.Scene.ai_server_status = bpy.props.StringProperty(
        name="Estado del servidor",
        description="Estado del servidor TCP para la ventana externa",
        default="",
    )


def unregister_scene_props():
    props = [
        "ai_provider", "ai_prompt", "ai_commands_json", "ai_commands_text",
        "ai_refine_instruction", "ai_auto_execute", "ai_status",
        "use_composition", "composition_type", "composition_style",
        "ai_history", "ai_history_index", "ai_server_status",
    ]
    for prop in props:
        try:
            delattr(bpy.types.Scene, prop)
        except AttributeError:
            pass


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    register_scene_props()
    print("Addon 'Generador AI de Objetos' (v2.0) registrado.")
    if not (LIB_GOOGLE or LIB_OPENAI or LIB_ANTHROPIC):
        print("ADVERTENCIA: Ninguna libreria de IA instalada. Revisa las Preferencias del addon.")


def unregister():
    _detener_servidor()
    unregister_scene_props()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    print("Addon 'Generador AI de Objetos' desregistrado.")


if __name__ == "__main__":
    try:
        unregister()
    except Exception as e:
        print(f"Error durante desregistro previo (puede ser normal al recargar): {e}")
    register()
