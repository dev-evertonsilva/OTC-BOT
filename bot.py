# py -m pip install -r requirements.txt

import ctypes
import json
import os
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import keyboard
import mouse
import pyautogui
import requests
import win32api
import win32con
import win32gui
import win32process
from PyQt6.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# ==================== ENUMS ====================


class ActionType(Enum):
    BLANK = 0
    SPELL = 1
    ITEM = 2
    HOTKEY = 3
    MACRO = 4


class MessageType(Enum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class TargetType(Enum):
    SELF = "self"
    TARGET = "target"
    FRIEND = "friend"
    CROSSHAIR = "crosshair"


class ConditionType(Enum):
    HP_BELOW = "hp_below"
    HP_ABOVE = "hp_above"
    MANA_BELOW = "mana_below"
    MANA_ABOVE = "mana_above"
    HAS_TARGET = "has_target"
    NO_TARGET = "no_target"
    COOLDOWN_READY = "cooldown_ready"
    ALWAYS = "always"


class MacroEventType(Enum):
    """Tipos de evento para gravação de macro"""

    KEY_DOWN = "key_down"
    KEY_UP = "key_up"
    MOUSE_MOVE = "mouse_move"
    MOUSE_CLICK = "mouse_click"
    MOUSE_SCROLL = "mouse_scroll"
    DELAY = "delay"


class WaypointType(Enum):
    """Tipos de waypoint para o CaveBot"""

    WALK = "walk"  # Andar até a posição
    ROPE = "rope"  # Usar rope
    SHOVEL = "shovel"  # Usar shovel
    LADDER = "ladder"  # Subir escada
    SEWER = "sewer"  # Descer bueiro
    STAND = "stand"  # Ficar parado (esperar)
    ACTION = "action"  # Executar ação (hotkey)
    LABEL = "label"  # Marcador para loops
    LURE = "lure"  # Posição de lure
    NODE = "node"  # Ponto de decisão


# ==================== DATA CLASSES ====================


@dataclass
class Macro:
    """Representa uma macro - ação executada periodicamente"""

    name: str
    callback: Callable
    timeout: int = 100  # ms
    enabled: bool = True
    last_execution: float = 0
    hotkey: str = ""
    switch: Optional[QCheckBox] = None

    def can_execute(self, now: float) -> bool:
        return self.enabled and (now - self.last_execution) >= (self.timeout / 1000)


@dataclass
class Hotkey:
    """Representa uma hotkey - ação executada ao pressionar tecla"""

    key: str
    callback: Callable
    single: bool = True  # single press vs hold
    enabled: bool = True
    last_execution: float = 0
    switch: Optional[QCheckBox] = None


@dataclass
class ScheduledTask:
    """Tarefa agendada para execução futura"""

    execution_time: float
    callback: Callable
    name: str = ""


@dataclass
class HealingRule:
    """Regra de healing automático"""

    name: str
    enabled: bool = True
    hotkey: str = "F1"
    threshold: int = 50  # % de HP/Mana
    condition: ConditionType = ConditionType.HP_BELOW
    target: TargetType = TargetType.SELF
    cooldown: float = 1.0
    last_used: float = 0
    priority: int = 0
    spell_name: str = ""
    mana_cost: int = 0


@dataclass
class PlayerState:
    """Estado atual do jogador"""

    hp: int = 100
    hp_max: int = 100
    mana: int = 100
    mana_max: int = 100
    hp_percent: float = 100.0
    mana_percent: float = 100.0
    is_poisoned: bool = False
    is_burning: bool = False
    is_electrified: bool = False
    is_cursed: bool = False
    is_paralyzed: bool = False
    is_hasted: bool = False
    is_invisible: bool = False
    has_mana_shield: bool = False
    has_target: bool = False
    is_attacking: bool = False
    is_following: bool = False
    position: Tuple[int, int, int] = (0, 0, 0)


@dataclass
class FriendState:
    """Estado de um amigo para party healing"""

    name: str
    hp_percent: float = 100.0
    position: Tuple[int, int, int] = (0, 0, 0)
    distance: int = 0
    is_visible: bool = True


@dataclass
class Waypoint:
    """Representa um waypoint do CaveBot"""

    x: int
    y: int
    z: int
    waypoint_type: WaypointType = WaypointType.WALK
    action: str = ""  # Hotkey ou ação a executar
    label: str = ""  # Nome do label (para LABEL e jumps)
    delay: int = 0  # Delay em ms antes de executar

    def to_dict(self) -> dict:
        return {
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "type": self.waypoint_type.value,
            "action": self.action,
            "label": self.label,
            "delay": self.delay,
        }

    @staticmethod
    def from_dict(data: dict) -> "Waypoint":
        return Waypoint(
            x=data["x"],
            y=data["y"],
            z=data["z"],
            waypoint_type=WaypointType(data.get("type", "walk")),
            action=data.get("action", ""),
            label=data.get("label", ""),
            delay=data.get("delay", 0),
        )

    def __str__(self) -> str:
        type_str = self.waypoint_type.value.upper()
        pos_str = f"({self.x}, {self.y}, {self.z})"
        if self.waypoint_type == WaypointType.LABEL:
            return f"[{type_str}] {self.label}"
        elif self.waypoint_type == WaypointType.ACTION:
            return f"[{type_str}] {pos_str} -> {self.action}"
        else:
            return f"[{type_str}] {pos_str}"


@dataclass
class MacroEvent:
    """Representa um evento gravado (tecla ou mouse)"""

    event_type: MacroEventType
    timestamp: float = 0
    key: str = ""
    x: int = 0
    y: int = 0
    button: str = ""
    delta: int = 0  # Para scroll

    def to_dict(self) -> dict:
        return {
            "type": self.event_type.value,
            "timestamp": self.timestamp,
            "key": self.key,
            "x": self.x,
            "y": self.y,
            "button": self.button,
            "delta": self.delta,
        }

    @staticmethod
    def from_dict(data: dict) -> "MacroEvent":
        return MacroEvent(
            event_type=MacroEventType(data["type"]),
            timestamp=data.get("timestamp", 0),
            key=data.get("key", ""),
            x=data.get("x", 0),
            y=data.get("y", 0),
            button=data.get("button", ""),
            delta=data.get("delta", 0),
        )

    def __str__(self) -> str:
        if self.event_type == MacroEventType.KEY_DOWN:
            return f"[KEY] {self.key} ↓"
        elif self.event_type == MacroEventType.KEY_UP:
            return f"[KEY] {self.key} ↑"
        elif self.event_type == MacroEventType.MOUSE_CLICK:
            return f"[CLICK] {self.button} @ ({self.x}, {self.y})"
        elif self.event_type == MacroEventType.MOUSE_MOVE:
            return f"[MOVE] ({self.x}, {self.y})"
        elif self.event_type == MacroEventType.MOUSE_SCROLL:
            return f"[SCROLL] {self.delta}"
        elif self.event_type == MacroEventType.DELAY:
            return f"[DELAY] {self.timestamp:.0f}ms"
        return f"[{self.event_type.value}]"


class MacroRecorder:
    """Gravador de macros de teclado e mouse"""

    def __init__(self):
        self.events: List[MacroEvent] = []
        self.recording: bool = False
        self.playing: bool = False
        self.start_time: float = 0
        self.loop: bool = False
        self.speed: float = 1.0  # Multiplicador de velocidade
        self._stop_playback: bool = False
        self._playback_thread: Optional[threading.Thread] = None

        # Configurações
        self.record_mouse_move: bool = False  # Mouse move gera muitos eventos
        self.record_keys: bool = True
        self.record_clicks: bool = True
        self.min_move_distance: int = 10  # Distância mínima para gravar movimento
        self._last_mouse_pos: Tuple[int, int] = (0, 0)

        # Janela alvo (OTClient)
        self.target_window: Optional[int] = None
        self.target_window_title: str = ""

    def find_otclient_window(self) -> Optional[int]:
        """Encontra a janela do OTClient"""
        result = []

        def enum_callback(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                # Procura por janelas que parecem ser OTClient
                if any(
                    x in title.lower()
                    for x in ["otclient", "tibia", "everleaf", "client"]
                ):
                    result.append((hwnd, title))
            return True

        try:
            win32gui.EnumWindows(enum_callback, None)
            if result:
                self.target_window = result[0][0]
                self.target_window_title = result[0][1]
                print(f"[MacroRecorder] Janela encontrada: {self.target_window_title}")
                return self.target_window
        except Exception as e:
            print(f"[MacroRecorder] Erro ao buscar janela: {e}")

        return None

    def focus_target_window(self) -> bool:
        """Foca na janela do OTClient"""
        if not self.target_window:
            self.find_otclient_window()

        if self.target_window:
            try:
                # Traz a janela para frente
                win32gui.SetForegroundWindow(self.target_window)
                time.sleep(0.05)  # Pequeno delay para garantir foco
                return True
            except Exception as e:
                print(f"[MacroRecorder] Erro ao focar janela: {e}")
                # Tenta encontrar novamente
                self.target_window = None
                self.find_otclient_window()

        return False

    def start_recording(self):
        """Inicia gravação"""
        if self.recording:
            return

        self.events.clear()
        self.recording = True
        self.start_time = time.time()
        self._last_mouse_pos = pyautogui.position()

        # Hooks de teclado
        if self.record_keys:
            keyboard.on_press(self._on_key_down)
            keyboard.on_release(self._on_key_up)

        # Hooks de mouse
        if self.record_clicks:
            mouse.on_click(self._on_mouse_click)
        if self.record_mouse_move:
            mouse.on_move(self._on_mouse_move)

        print("[MacroRecorder] Gravação iniciada!")

    def stop_recording(self):
        """Para gravação"""
        if not self.recording:
            return

        self.recording = False

        # Remove hooks
        try:
            keyboard.unhook_all()
            mouse.unhook_all()
        except:
            pass

        print(f"[MacroRecorder] Gravação parada! {len(self.events)} eventos gravados.")

    def _get_elapsed(self) -> float:
        """Retorna tempo desde o início da gravação em ms"""
        return (time.time() - self.start_time) * 1000

    def _on_key_down(self, event):
        """Callback de tecla pressionada"""
        if not self.recording:
            return

        # Ignora teclas de controle da gravação
        if event.name in ["f6", "f7"]:
            return

        self.events.append(
            MacroEvent(
                event_type=MacroEventType.KEY_DOWN,
                timestamp=self._get_elapsed(),
                key=event.name,
            )
        )

    def _on_key_up(self, event):
        """Callback de tecla solta"""
        if not self.recording:
            return

        if event.name in ["f6", "f7"]:
            return

        self.events.append(
            MacroEvent(
                event_type=MacroEventType.KEY_UP,
                timestamp=self._get_elapsed(),
                key=event.name,
            )
        )

    def _on_mouse_click(self, event=None):
        """Callback de clique do mouse"""
        if not self.recording:
            return

        x, y = pyautogui.position()
        button = "left"
        if hasattr(event, "button"):
            button = event.button

        self.events.append(
            MacroEvent(
                event_type=MacroEventType.MOUSE_CLICK,
                timestamp=self._get_elapsed(),
                x=x,
                y=y,
                button=button,
            )
        )

    def _on_mouse_move(self, event=None):
        """Callback de movimento do mouse"""
        if not self.recording:
            return

        x, y = pyautogui.position()

        # Só grava se moveu distância mínima
        dx = abs(x - self._last_mouse_pos[0])
        dy = abs(y - self._last_mouse_pos[1])
        if dx < self.min_move_distance and dy < self.min_move_distance:
            return

        self._last_mouse_pos = (x, y)

        self.events.append(
            MacroEvent(
                event_type=MacroEventType.MOUSE_MOVE,
                timestamp=self._get_elapsed(),
                x=x,
                y=y,
            )
        )

    def play(self, loop: bool = False):
        """Reproduz a macro gravada"""
        if not self.events or self.playing:
            return

        # Encontra e foca a janela do OTClient
        self.find_otclient_window()

        self.playing = True
        self.loop = loop
        self._stop_playback = False

        def playback_thread():
            print(f"[MacroRecorder] Iniciando reprodução (loop={self.loop})")

            iteration = 0
            while not self._stop_playback:
                iteration += 1
                print(f"[MacroRecorder] Iteração {iteration}")

                # Foca a janela antes de cada iteração
                self.focus_target_window()
                time.sleep(0.1)

                last_time = 0

                for event in self.events:
                    if self._stop_playback:
                        break

                    # Calcula delay
                    delay = (event.timestamp - last_time) / 1000 / self.speed
                    if delay > 0:
                        time.sleep(delay)
                    last_time = event.timestamp

                    # Executa evento
                    self._execute_event(event)

                # Verifica se deve continuar o loop
                if not self.loop or self._stop_playback:
                    break

                # Pequeno delay entre iterações
                time.sleep(0.2)

            self.playing = False
            print("[MacroRecorder] Reprodução finalizada!")

        self._playback_thread = threading.Thread(target=playback_thread, daemon=True)
        self._playback_thread.start()

    def stop_playback(self):
        """Para a reprodução"""
        self._stop_playback = True
        self.playing = False

    def _execute_event(self, event: MacroEvent):
        """Executa um evento gravado"""
        try:
            if event.event_type == MacroEventType.KEY_DOWN:
                # Usa keyboard.press que funciona globalmente
                keyboard.press(event.key)
            elif event.event_type == MacroEventType.KEY_UP:
                keyboard.release(event.key)
            elif event.event_type == MacroEventType.MOUSE_CLICK:
                # Move o mouse e clica
                pyautogui.click(event.x, event.y, button=event.button, _pause=False)
            elif event.event_type == MacroEventType.MOUSE_MOVE:
                pyautogui.moveTo(event.x, event.y, _pause=False)
            elif event.event_type == MacroEventType.MOUSE_SCROLL:
                pyautogui.scroll(event.delta, _pause=False)
        except Exception as e:
            print(f"[MacroRecorder] Erro ao executar evento: {e}")

    def send_key_to_window(self, key: str, press: bool = True):
        """Envia tecla diretamente para a janela alvo usando PostMessage"""
        if not self.target_window:
            return

        # Mapeamento de teclas para Virtual Key Codes
        VK_CODES = {
            "up": 0x26,
            "down": 0x28,
            "left": 0x25,
            "right": 0x27,
            "space": 0x20,
            "enter": 0x0D,
            "escape": 0x1B,
            "tab": 0x09,
            "shift": 0x10,
            "ctrl": 0x11,
            "alt": 0x12,
            "f1": 0x70,
            "f2": 0x71,
            "f3": 0x72,
            "f4": 0x73,
            "f5": 0x74,
            "f6": 0x75,
            "f7": 0x76,
            "f8": 0x77,
            "f9": 0x78,
            "f10": 0x79,
            "f11": 0x7A,
            "f12": 0x7B,
            "a": 0x41,
            "b": 0x42,
            "c": 0x43,
            "d": 0x44,
            "e": 0x45,
            "f": 0x46,
            "g": 0x47,
            "h": 0x48,
            "i": 0x49,
            "j": 0x4A,
            "k": 0x4B,
            "l": 0x4C,
            "m": 0x4D,
            "n": 0x4E,
            "o": 0x4F,
            "p": 0x50,
            "q": 0x51,
            "r": 0x52,
            "s": 0x53,
            "t": 0x54,
            "u": 0x55,
            "v": 0x56,
            "w": 0x57,
            "x": 0x58,
            "y": 0x59,
            "z": 0x5A,
            "0": 0x30,
            "1": 0x31,
            "2": 0x32,
            "3": 0x33,
            "4": 0x34,
            "5": 0x35,
            "6": 0x36,
            "7": 0x37,
            "8": 0x38,
            "9": 0x39,
        }

        key_lower = key.lower()
        if key_lower in VK_CODES:
            vk_code = VK_CODES[key_lower]
            try:
                if press:
                    win32api.PostMessage(
                        self.target_window, win32con.WM_KEYDOWN, vk_code, 0
                    )
                else:
                    win32api.PostMessage(
                        self.target_window, win32con.WM_KEYUP, vk_code, 0
                    )
            except Exception as e:
                print(f"[MacroRecorder] Erro ao enviar tecla: {e}")

    def save(self, filepath: str):
        """Salva macro em arquivo JSON"""
        data = {
            "events": [e.to_dict() for e in self.events],
            "total_time": self.events[-1].timestamp if self.events else 0,
            "event_count": len(self.events),
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"[MacroRecorder] Macro salva: {filepath}")

    def load(self, filepath: str):
        """Carrega macro de arquivo JSON"""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.events = [MacroEvent.from_dict(e) for e in data.get("events", [])]
        print(f"[MacroRecorder] Macro carregada: {len(self.events)} eventos")

    def clear(self):
        """Limpa eventos gravados"""
        self.events.clear()


# ==================== CALLBACK SYSTEM ====================


class CallbackManager(QObject):
    """Gerenciador de callbacks - similar ao sistema de callbacks do Lua"""

    # Sinais PyQt para diferentes eventos
    on_key_down = pyqtSignal(str)
    on_key_up = pyqtSignal(str)
    on_key_press = pyqtSignal(str, int)
    on_hp_change = pyqtSignal(int, int, int, int)  # hp, maxHp, oldHp, oldMaxHp
    on_mana_change = pyqtSignal(int, int, int, int)
    on_state_change = pyqtSignal(dict, dict)  # newStates, oldStates
    on_target_change = pyqtSignal(bool)  # hasTarget
    on_text_message = pyqtSignal(str, str)  # mode, text
    on_position_change = pyqtSignal(tuple, tuple)  # newPos, oldPos

    def __init__(self):
        super().__init__()
        self._callbacks: Dict[str, List[Callable]] = {
            "onKeyDown": [],
            "onKeyUp": [],
            "onKeyPress": [],
            "onHpChange": [],
            "onManaChange": [],
            "onStateChange": [],
            "onTargetChange": [],
            "onTextMessage": [],
            "onPositionChange": [],
            "onTick": [],  # chamado a cada ciclo do bot
        }

    def register(self, event: str, callback: Callable):
        """Registra um callback para um evento"""
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def unregister(self, event: str, callback: Callable):
        """Remove um callback de um evento"""
        if event in self._callbacks and callback in self._callbacks[event]:
            self._callbacks[event].remove(callback)

    def trigger(self, event: str, *args, **kwargs):
        """Dispara todos os callbacks de um evento"""
        if event in self._callbacks:
            for callback in self._callbacks[event]:
                try:
                    callback(*args, **kwargs)
                except Exception as e:
                    print(f"[ERROR] Callback {event} error: {e}")


# ==================== STORAGE SYSTEM ====================


class BotStorage:
    """Sistema de armazenamento persistente - similar ao storage do Lua"""

    def __init__(self, storage_dir: str = "bot_storage"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(exist_ok=True)
        self._data: Dict[str, Any] = {}
        self._file_path: Optional[Path] = None

    def load(self, profile_name: str = "default"):
        """Carrega dados de um perfil"""
        self._file_path = self.storage_dir / f"{profile_name}.json"
        if self._file_path.exists():
            try:
                with open(self._file_path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except Exception as e:
                print(f"[ERROR] Failed to load storage: {e}")
                self._data = {}
        else:
            self._data = {}

    def save(self):
        """Salva dados no arquivo"""
        if self._file_path:
            try:
                with open(self._file_path, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"[ERROR] Failed to save storage: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """Obtém um valor do storage"""
        return self._data.get(key, default)

    def set(self, key: str, value: Any):
        """Define um valor no storage"""
        self._data[key] = value

    def delete(self, key: str):
        """Remove uma chave do storage"""
        if key in self._data:
            del self._data[key]

    @property
    def data(self) -> Dict[str, Any]:
        return self._data


# ==================== SCHEDULER SYSTEM ====================


class Scheduler:
    """Sistema de agendamento de tarefas - similar ao scheduler do Lua"""

    def __init__(self):
        self._tasks: List[ScheduledTask] = []

    def schedule(self, delay_ms: int, callback: Callable, name: str = ""):
        """Agenda uma tarefa para execução futura"""
        execution_time = time.time() + (delay_ms / 1000)
        task = ScheduledTask(execution_time, callback, name)
        self._tasks.append(task)
        self._tasks.sort(key=lambda t: t.execution_time)

    def cancel(self, name: str):
        """Cancela uma tarefa agendada pelo nome"""
        self._tasks = [t for t in self._tasks if t.name != name]

    def clear(self):
        """Remove todas as tarefas agendadas"""
        self._tasks.clear()

    def process(self):
        """Processa tarefas que estão prontas para execução"""
        now = time.time()
        while self._tasks and self._tasks[0].execution_time <= now:
            task = self._tasks.pop(0)
            try:
                task.callback()
            except Exception as e:
                print(f"[ERROR] Scheduled task error: {e}")


# ==================== POSITION READER ====================


class PositionFileHandler(FileSystemEventHandler):
    """Handler para monitorar mudanças no arquivo de posição"""

    def __init__(self, callback: Callable):
        self.callback = callback

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith("position.json"):
            self.callback()


class PositionReader:
    """
    Sistema de leitura de posição do player.
    Suporta múltiplos métodos:
    - Arquivo JSON (exportado pelo OTClient)
    - HTTP/WebSocket (comunicação com OTClient)
    - Manual (entrada do usuário)
    """

    def __init__(self, executor: "BotExecutor"):
        self.executor = executor
        self.method = "file"  # file, http, manual
        self.position_file = "player_position.json"
        self.http_url = "http://localhost:8080/position"
        self.update_interval = 100  # ms

        # File watcher
        self._observer: Optional[Observer] = None
        self._watch_path: Optional[str] = None

        # Última posição lida
        self._last_position: Tuple[int, int, int] = (0, 0, 0)
        self._last_read_time: float = 0

    def start_file_watcher(self, filepath: str):
        """Inicia monitoramento de arquivo de posição"""
        self._watch_path = filepath
        directory = os.path.dirname(filepath) or "."

        self._observer = Observer()
        handler = PositionFileHandler(self._on_file_change)
        self._observer.schedule(handler, directory, recursive=False)
        self._observer.start()
        self.executor.info(f"Monitorando arquivo: {filepath}")

    def stop_file_watcher(self):
        """Para o monitoramento de arquivo"""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None

    def _on_file_change(self):
        """Callback quando o arquivo de posição muda"""
        pos = self.read_from_file(self._watch_path)
        if pos:
            self._update_position(pos)

    def read_from_file(self, filepath: str) -> Optional[Tuple[int, int, int]]:
        """Lê posição de um arquivo JSON"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                x = data.get("x", data.get("posx", 0))
                y = data.get("y", data.get("posy", 0))
                z = data.get("z", data.get("posz", 0))
                return (x, y, z)
        except Exception as e:
            return None

    def read_from_http(self) -> Optional[Tuple[int, int, int]]:
        """Lê posição via HTTP do OTClient"""
        try:
            response = requests.get(self.http_url, timeout=0.5)
            if response.status_code == 200:
                data = response.json()
                x = data.get("x", data.get("posx", 0))
                y = data.get("y", data.get("posy", 0))
                z = data.get("z", data.get("posz", 0))

                # Também pode ler HP/Mana se disponível
                if "hp" in data and "maxHp" in data:
                    self.executor.update_player_hp(data["hp"], data["maxHp"])
                if "mana" in data and "maxMana" in data:
                    self.executor.update_player_mana(data["mana"], data["maxMana"])

                return (x, y, z)
        except Exception as e:
            return None
        return None

    def read_position(self) -> Tuple[int, int, int]:
        """Lê a posição atual baseado no método configurado"""
        now = time.time()

        # Rate limiting
        if (now - self._last_read_time) * 1000 < self.update_interval:
            return self._last_position

        pos = None

        if self.method == "file":
            pos = self.read_from_file(self.position_file)
        elif self.method == "http":
            pos = self.read_from_http()
        elif self.method == "manual":
            pos = self._last_position

        if pos:
            self._update_position(pos)
            self._last_read_time = now

        return self._last_position

    def _update_position(self, pos: Tuple[int, int, int]):
        """Atualiza a posição e notifica o executor"""
        old_pos = self._last_position
        self._last_position = pos
        self.executor.player.position = pos

        if old_pos != pos:
            self.executor.callbacks.trigger("onPositionChange", pos, old_pos)

    def set_position_manual(self, x: int, y: int, z: int):
        """Define posição manualmente"""
        self._update_position((x, y, z))

    def get_position(self) -> Tuple[int, int, int]:
        """Retorna a última posição conhecida"""
        return self._last_position


# ==================== BOT EXECUTOR ====================


class CaveBot:
    """Sistema de CaveBot com waypoints"""

    def __init__(self, executor: "BotExecutor"):
        self.executor = executor
        self.waypoints: List[Waypoint] = []
        self.current_index: int = 0
        self.enabled: bool = False
        self.paused: bool = False
        self.last_move_time: float = 0
        self.move_delay: int = 200  # ms entre movimentos
        self.stuck_count: int = 0
        self.max_stuck: int = 5
        self.last_position: Tuple[int, int, int] = (0, 0, 0)

        # Configurações de captura de posição
        self.game_window_region: Optional[Tuple[int, int, int, int]] = None
        self.minimap_region: Optional[Tuple[int, int, int, int]] = None

        # Labels para navegação
        self.labels: Dict[str, int] = {}  # label_name -> waypoint_index

    def add_waypoint(self, waypoint: Waypoint):
        """Adiciona um waypoint à lista"""
        self.waypoints.append(waypoint)
        if waypoint.waypoint_type == WaypointType.LABEL:
            self.labels[waypoint.label] = len(self.waypoints) - 1

    def insert_waypoint(self, index: int, waypoint: Waypoint):
        """Insere um waypoint em uma posição específica"""
        self.waypoints.insert(index, waypoint)
        self._rebuild_labels()

    def remove_waypoint(self, index: int):
        """Remove um waypoint pelo índice"""
        if 0 <= index < len(self.waypoints):
            self.waypoints.pop(index)
            self._rebuild_labels()
            if self.current_index >= len(self.waypoints):
                self.current_index = 0

    def clear_waypoints(self):
        """Limpa todos os waypoints"""
        self.waypoints.clear()
        self.labels.clear()
        self.current_index = 0

    def _rebuild_labels(self):
        """Reconstrói o dicionário de labels"""
        self.labels.clear()
        for i, wp in enumerate(self.waypoints):
            if wp.waypoint_type == WaypointType.LABEL:
                self.labels[wp.label] = i

    def goto_label(self, label: str) -> bool:
        """Pula para um label específico"""
        if label in self.labels:
            self.current_index = self.labels[label]
            return True
        return False

    def get_current_waypoint(self) -> Optional[Waypoint]:
        """Retorna o waypoint atual"""
        if 0 <= self.current_index < len(self.waypoints):
            return self.waypoints[self.current_index]
        return None

    def next_waypoint(self):
        """Avança para o próximo waypoint"""
        self.current_index += 1
        if self.current_index >= len(self.waypoints):
            self.current_index = 0  # Loop

    def previous_waypoint(self):
        """Volta para o waypoint anterior"""
        self.current_index -= 1
        if self.current_index < 0:
            self.current_index = len(self.waypoints) - 1

    def tick(self):
        """Executa um tick do cavebot"""
        # Não faz nada se não estiver ativo, pausado ou sem waypoints
        if not self.enabled or self.paused:
            return

        # Se não tem waypoints, não faz nada (não é erro)
        if not self.waypoints or len(self.waypoints) == 0:
            return

        now = time.time()
        if (now - self.last_move_time) * 1000 < self.move_delay:
            return

        waypoint = self.get_current_waypoint()
        if not waypoint:
            return

        # Verifica se chegou no waypoint
        player_pos = self.executor.player.position

        # Se a posição ainda não foi lida (0,0,0), aguarda
        if player_pos == (0, 0, 0):
            return

        if waypoint.waypoint_type == WaypointType.LABEL:
            # Labels são apenas marcadores, pula
            self.next_waypoint()
            return

        # Verifica se está na posição do waypoint
        if self._is_at_position(player_pos, (waypoint.x, waypoint.y, waypoint.z)):
            self._execute_waypoint(waypoint)
            self.next_waypoint()
            self.stuck_count = 0
            self.executor.info(f"Waypoint {self.current_index} alcançado!")
        else:
            # Precisa andar até o waypoint
            self._walk_to_waypoint(waypoint)

            # Verifica se está travado (só se a posição anterior não era 0,0,0)
            if self.last_position != (0, 0, 0) and player_pos == self.last_position:
                self.stuck_count += 1
                if self.stuck_count >= self.max_stuck:
                    self.executor.warn(f"CaveBot travado! Tentando destravar...")
                    self._handle_stuck()
            else:
                self.stuck_count = 0

        self.last_position = player_pos
        self.last_move_time = now

    def _is_at_position(
        self, pos1: Tuple[int, int, int], pos2: Tuple[int, int, int]
    ) -> bool:
        """Verifica se duas posições são iguais ou adjacentes"""
        return pos1[0] == pos2[0] and pos1[1] == pos2[1] and pos1[2] == pos2[2]

    def _execute_waypoint(self, waypoint: Waypoint):
        """Executa a ação de um waypoint"""
        if waypoint.delay > 0:
            time.sleep(waypoint.delay / 1000)

        if waypoint.waypoint_type == WaypointType.ACTION:
            if waypoint.action:
                self.executor.press_key(waypoint.action)
        elif waypoint.waypoint_type == WaypointType.ROPE:
            self.executor.press_key(self.executor.storage.get("rope_hotkey", "r"))
        elif waypoint.waypoint_type == WaypointType.SHOVEL:
            self.executor.press_key(self.executor.storage.get("shovel_hotkey", "o"))
        elif waypoint.waypoint_type == WaypointType.STAND:
            time.sleep(waypoint.delay / 1000 if waypoint.delay > 0 else 1)

    def _walk_to_waypoint(self, waypoint: Waypoint):
        """Anda até um waypoint usando click no minimapa ou teclas direcionais"""
        player_pos = self.executor.player.position
        dx = waypoint.x - player_pos[0]
        dy = waypoint.y - player_pos[1]

        # Usa teclas direcionais para movimento
        if dx > 0:
            keyboard.press_and_release("right")
        elif dx < 0:
            keyboard.press_and_release("left")

        if dy > 0:
            keyboard.press_and_release("down")
        elif dy < 0:
            keyboard.press_and_release("up")

    def _handle_stuck(self):
        """Tenta destravar quando o bot está preso"""
        # Tenta movimentos aleatórios
        import random

        directions = ["up", "down", "left", "right"]
        for _ in range(3):
            key = random.choice(directions)
            keyboard.press_and_release(key)
            time.sleep(0.2)
        self.stuck_count = 0

    def save_waypoints(self, filepath: str):
        """Salva waypoints em arquivo JSON"""
        data = {
            "waypoints": [wp.to_dict() for wp in self.waypoints],
            "move_delay": self.move_delay,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def load_waypoints(self, filepath: str):
        """Carrega waypoints de arquivo JSON"""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.waypoints = [Waypoint.from_dict(wp) for wp in data.get("waypoints", [])]
        self.move_delay = data.get("move_delay", 200)
        self._rebuild_labels()
        self.current_index = 0

    def record_position(
        self, x: int, y: int, z: int, wp_type: WaypointType = WaypointType.WALK
    ):
        """Grava uma posição como waypoint"""
        waypoint = Waypoint(x=x, y=y, z=z, waypoint_type=wp_type)
        self.add_waypoint(waypoint)
        self.executor.info(f"Waypoint gravado: {waypoint}")
        return waypoint


class BotExecutor(QObject):
    """Executor principal do bot - similar ao executor.lua"""

    message_signal = pyqtSignal(str, str)  # category, message
    status_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        # Tempo atual
        self.now: float = time.time()

        # Estado do jogador
        self.player = PlayerState()

        # Sistemas
        self.callbacks = CallbackManager()
        self.storage = BotStorage()
        self.scheduler = Scheduler()

        # Macros e Hotkeys
        self._macros: List[Macro] = []
        self._hotkeys: Dict[str, Hotkey] = {}

        # Regras de healing
        self.healing_rules: List[HealingRule] = []
        self.friend_healing_rules: List[HealingRule] = []

        # Amigos para party healing
        self.friends: Dict[str, FriendState] = {}

        # CaveBot
        self.cavebot = CaveBot(self)

        # Position Reader
        self.position_reader = PositionReader(self)

        # Estado
        self.active = False
        self.check_interval = 50  # ms - intervalo de verificação

        # Cooldowns de spells (spell_id -> ready_time)
        self._spell_cooldowns: Dict[str, float] = {}
        self._group_cooldowns: Dict[int, float] = {}

        # Keyboard listener
        self._keyboard_hooks = []

    def start(self):
        """Inicia o executor"""
        self.active = True
        self._setup_keyboard_hooks()
        self.info("Bot iniciado!")

    def stop(self):
        """Para o executor"""
        self.active = False
        self._remove_keyboard_hooks()
        self.info("Bot parado!")

    def _setup_keyboard_hooks(self):
        """Configura os hooks de teclado"""
        try:
            keyboard.on_press(self._on_key_down)
            keyboard.on_release(self._on_key_up)
        except Exception as e:
            self.error(f"Erro ao configurar teclado: {e}")

    def _remove_keyboard_hooks(self):
        """Remove os hooks de teclado"""
        try:
            keyboard.unhook_all()
        except:
            pass

    def _on_key_down(self, event):
        """Callback de tecla pressionada"""
        if not self.active:
            return

        key_desc = event.name
        if event.event_type == "down":
            # Verifica hotkeys
            for hotkey_key, hotkey in self._hotkeys.items():
                if hotkey.enabled and hotkey_key.lower() == key_desc.lower():
                    if hotkey.single:
                        try:
                            hotkey.callback()
                            hotkey.last_execution = self.now
                        except Exception as e:
                            self.error(f"Hotkey {hotkey_key} error: {e}")

            # Trigger callback
            self.callbacks.trigger("onKeyDown", key_desc)

    def _on_key_up(self, event):
        """Callback de tecla solta"""
        if not self.active:
            return

        key_desc = event.name
        self.callbacks.trigger("onKeyUp", key_desc)

    def tick(self):
        """Chamado a cada ciclo do bot"""
        if not self.active:
            return

        self.now = time.time()

        # Processa scheduler
        self.scheduler.process()

        # Executa macros
        for macro in self._macros:
            if macro.can_execute(self.now):
                try:
                    result = macro.callback(macro)
                    if result:
                        macro.last_execution = self.now
                except Exception as e:
                    self.error(f"Macro {macro.name} error: {e}")

        # Lê posição atual
        if self.position_reader.method != "manual":
            self.position_reader.read_position()

        # Executa CaveBot
        if self.cavebot.enabled:
            self.cavebot.tick()

        # Trigger tick callback
        self.callbacks.trigger("onTick")

    # ==================== MACRO FUNCTIONS ====================

    def add_macro(
        self,
        name: str,
        callback: Callable,
        timeout: int = 100,
        hotkey: str = "",
        enabled: bool = True,
    ) -> Macro:
        """Adiciona uma nova macro"""
        macro = Macro(
            name=name,
            callback=callback,
            timeout=timeout,
            hotkey=hotkey,
            enabled=enabled,
        )
        self._macros.append(macro)
        return macro

    def remove_macro(self, name: str):
        """Remove uma macro pelo nome"""
        self._macros = [m for m in self._macros if m.name != name]

    def get_macro(self, name: str) -> Optional[Macro]:
        """Obtém uma macro pelo nome"""
        for macro in self._macros:
            if macro.name == name:
                return macro
        return None

    # ==================== HOTKEY FUNCTIONS ====================

    def add_hotkey(self, key: str, callback: Callable, single: bool = True) -> Hotkey:
        """Adiciona uma nova hotkey"""
        hotkey = Hotkey(key=key, callback=callback, single=single)
        self._hotkeys[key] = hotkey
        return hotkey

    def remove_hotkey(self, key: str):
        """Remove uma hotkey"""
        if key in self._hotkeys:
            del self._hotkeys[key]

    # ==================== SPELL COOLDOWN FUNCTIONS ====================

    def is_spell_ready(self, spell_id: str) -> bool:
        """Verifica se uma spell está pronta"""
        if spell_id not in self._spell_cooldowns:
            return True
        return self.now >= self._spell_cooldowns[spell_id]

    def is_group_ready(self, group_id: int) -> bool:
        """Verifica se um grupo de spells está pronto"""
        if group_id not in self._group_cooldowns:
            return True
        return self.now >= self._group_cooldowns[group_id]

    def set_spell_cooldown(self, spell_id: str, duration_ms: int):
        """Define cooldown de uma spell"""
        self._spell_cooldowns[spell_id] = self.now + (duration_ms / 1000)

    def set_group_cooldown(self, group_id: int, duration_ms: int):
        """Define cooldown de um grupo"""
        self._group_cooldowns[group_id] = self.now + (duration_ms / 1000)

    # ==================== HEALING FUNCTIONS ====================

    def add_healing_rule(self, rule: HealingRule):
        """Adiciona uma regra de healing"""
        self.healing_rules.append(rule)
        self.healing_rules.sort(key=lambda r: r.priority, reverse=True)

    def remove_healing_rule(self, name: str):
        """Remove uma regra de healing"""
        self.healing_rules = [r for r in self.healing_rules if r.name != name]

    def check_healing(self) -> Optional[HealingRule]:
        """Verifica qual regra de healing deve ser executada"""
        for rule in self.healing_rules:
            if not rule.enabled:
                continue

            # Verifica cooldown
            if self.now - rule.last_used < rule.cooldown:
                continue

            # Verifica condição
            should_heal = False

            if rule.condition == ConditionType.HP_BELOW:
                should_heal = self.player.hp_percent < rule.threshold
            elif rule.condition == ConditionType.HP_ABOVE:
                should_heal = self.player.hp_percent > rule.threshold
            elif rule.condition == ConditionType.MANA_BELOW:
                should_heal = self.player.mana_percent < rule.threshold
            elif rule.condition == ConditionType.MANA_ABOVE:
                should_heal = self.player.mana_percent > rule.threshold
            elif rule.condition == ConditionType.HAS_TARGET:
                should_heal = self.player.has_target
            elif rule.condition == ConditionType.ALWAYS:
                should_heal = True

            if should_heal:
                return rule

        return None

    def execute_healing(self, rule: HealingRule) -> bool:
        """Executa uma regra de healing"""
        try:
            # Verifica mana suficiente
            if rule.mana_cost > 0 and self.player.mana < rule.mana_cost:
                return False

            # Executa hotkey
            keyboard.press_and_release(rule.hotkey)
            rule.last_used = self.now
            self.info(f"Executando: {rule.name}")
            return True
        except Exception as e:
            self.error(f"Erro ao executar healing {rule.name}: {e}")
            return False

    # ==================== FRIEND HEALING FUNCTIONS ====================

    def add_friend(self, name: str):
        """Adiciona um amigo para party healing"""
        self.friends[name] = FriendState(name=name)

    def remove_friend(self, name: str):
        """Remove um amigo"""
        if name in self.friends:
            del self.friends[name]

    def update_friend(
        self, name: str, hp_percent: float, position: Tuple[int, int, int] = None
    ):
        """Atualiza estado de um amigo"""
        if name in self.friends:
            self.friends[name].hp_percent = hp_percent
            if position:
                self.friends[name].position = position

    def check_friend_healing(self) -> Optional[Tuple[FriendState, HealingRule]]:
        """Verifica se algum amigo precisa de healing"""
        for rule in self.friend_healing_rules:
            if not rule.enabled:
                continue

            if self.now - rule.last_used < rule.cooldown:
                continue

            for friend in self.friends.values():
                if friend.hp_percent < rule.threshold and friend.is_visible:
                    return (friend, rule)

        return None

    # ==================== UTILITY FUNCTIONS ====================

    def press_key(self, key: str):
        """Pressiona uma tecla"""
        try:
            keyboard.press_and_release(key)
        except Exception as e:
            self.error(f"Erro ao pressionar tecla {key}: {e}")

    def say(self, text: str):
        """Digita texto (para usar spells por nome)"""
        try:
            keyboard.write(text)
            keyboard.press_and_release("enter")
        except Exception as e:
            self.error(f"Erro ao digitar: {e}")

    def use_item_on_self(self, hotkey: str):
        """Usa item no próprio personagem"""
        self.press_key(hotkey)

    def use_item_on_target(self, hotkey: str):
        """Usa item no target (crosshair)"""
        # Precisa implementar lógica de crosshair
        self.press_key(hotkey)

    # ==================== MESSAGE FUNCTIONS ====================

    def info(self, text: str):
        """Mensagem informativa"""
        self.message_signal.emit("info", str(text))
        print(f"[INFO] {text}")

    def warn(self, text: str):
        """Mensagem de aviso"""
        self.message_signal.emit("warn", str(text))
        print(f"[WARN] {text}")

    def error(self, text: str):
        """Mensagem de erro"""
        self.message_signal.emit("error", str(text))
        print(f"[ERROR] {text}")

    # ==================== STATE UPDATE FUNCTIONS ====================

    def update_player_hp(self, hp: int, hp_max: int):
        """Atualiza HP do jogador"""
        old_hp = self.player.hp
        old_hp_max = self.player.hp_max

        self.player.hp = hp
        self.player.hp_max = hp_max
        self.player.hp_percent = (hp / hp_max * 100) if hp_max > 0 else 0

        if hp != old_hp or hp_max != old_hp_max:
            self.callbacks.trigger("onHpChange", hp, hp_max, old_hp, old_hp_max)

    def update_player_mana(self, mana: int, mana_max: int):
        """Atualiza Mana do jogador"""
        old_mana = self.player.mana
        old_mana_max = self.player.mana_max

        self.player.mana = mana
        self.player.mana_max = mana_max
        self.player.mana_percent = (mana / mana_max * 100) if mana_max > 0 else 0

        if mana != old_mana or mana_max != old_mana_max:
            self.callbacks.trigger(
                "onManaChange", mana, mana_max, old_mana, old_mana_max
            )


# ==================== UI PANELS ====================


class HealingPanel(QWidget):
    """Painel de configuração de healing"""

    def __init__(self, executor: BotExecutor):
        super().__init__()
        self.executor = executor
        self.healing_widgets: List[Dict] = []
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # Scroll area para os slots
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        # Spell Healing
        spell_group = QGroupBox("Spell Healing")
        spell_layout = QVBoxLayout()

        for i in range(1, 5):
            slot = self._create_healing_slot(f"Spell {i}", f"spell_{i}")
            spell_layout.addLayout(slot)

        spell_group.setLayout(spell_layout)
        scroll_layout.addWidget(spell_group)

        # Potion Healing
        potion_group = QGroupBox("Potion Healing")
        potion_layout = QVBoxLayout()

        for i in range(1, 5):
            slot = self._create_healing_slot(f"Potion {i}", f"potion_{i}")
            potion_layout.addLayout(slot)

        potion_group.setLayout(potion_layout)
        scroll_layout.addWidget(potion_group)

        # Emergency Healing
        emergency_group = QGroupBox("Emergency Healing")
        emergency_layout = QVBoxLayout()

        for i in range(1, 3):
            slot = self._create_healing_slot(
                f"Emergency {i}", f"emergency_{i}", is_emergency=True
            )
            emergency_layout.addLayout(slot)

        emergency_group.setLayout(emergency_layout)
        scroll_layout.addWidget(emergency_group)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        self.setLayout(layout)

    def _create_healing_slot(
        self, name: str, slot_id: str, is_emergency: bool = False
    ) -> QHBoxLayout:
        """Cria um slot de healing"""
        layout = QHBoxLayout()

        # Enable checkbox
        enable = QCheckBox()
        enable.setObjectName(f"{slot_id}_enable")
        enable.setToolTip("Ativar/Desativar")
        layout.addWidget(enable)

        # Label
        label = QLabel(f"{name}:")
        label.setMinimumWidth(80)
        layout.addWidget(label)

        # Hotkey
        hotkey = QComboBox()
        hotkey.setEditable(True)
        hotkey.setMinimumWidth(70)
        keys = [
            "F1",
            "F2",
            "F3",
            "F4",
            "F5",
            "F6",
            "F7",
            "F8",
            "F9",
            "F10",
            "F11",
            "F12",
        ]
        hotkey.addItems(keys)
        hotkey.setObjectName(f"{slot_id}_hotkey")
        layout.addWidget(hotkey)

        # Condition
        condition = QComboBox()
        condition.addItems(["HP Below", "HP Above", "Mana Below", "Mana Above"])
        condition.setObjectName(f"{slot_id}_condition")
        layout.addWidget(condition)

        # Threshold
        threshold = QSpinBox()
        threshold.setRange(1, 100)
        threshold.setValue(50 if not is_emergency else 20)
        threshold.setSuffix("%")
        threshold.setObjectName(f"{slot_id}_threshold")
        layout.addWidget(threshold)

        # Store widget references
        self.healing_widgets.append(
            {
                "id": slot_id,
                "enable": enable,
                "hotkey": hotkey,
                "condition": condition,
                "threshold": threshold,
            }
        )

        return layout

    def get_rules(self) -> List[HealingRule]:
        """Retorna as regras de healing configuradas"""
        rules = []
        for i, widget in enumerate(self.healing_widgets):
            if widget["enable"].isChecked():
                condition_text = widget["condition"].currentText()
                condition = ConditionType.HP_BELOW
                if "HP Above" in condition_text:
                    condition = ConditionType.HP_ABOVE
                elif "Mana Below" in condition_text:
                    condition = ConditionType.MANA_BELOW
                elif "Mana Above" in condition_text:
                    condition = ConditionType.MANA_ABOVE

                rule = HealingRule(
                    name=widget["id"],
                    enabled=True,
                    hotkey=widget["hotkey"].currentText(),
                    threshold=widget["threshold"].value(),
                    condition=condition,
                    priority=len(self.healing_widgets) - i,
                )
                rules.append(rule)
        return rules


class ToolsPanel(QWidget):
    """Painel de ferramentas auxiliares"""

    def __init__(self, executor: BotExecutor):
        super().__init__()
        self.executor = executor
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        # Auto Haste
        haste_group = QGroupBox("Auto Haste")
        haste_layout = QVBoxLayout()

        self.enable_haste = QCheckBox("Ativar Auto Haste")
        haste_layout.addWidget(self.enable_haste)

        haste_settings = QHBoxLayout()
        haste_settings.addWidget(QLabel("Hotkey:"))
        self.haste_hotkey = QComboBox()
        self.haste_hotkey.setEditable(True)
        self.haste_hotkey.addItems(["ctrl+1", "ctrl+2", "ctrl+3", "ctrl+4"])
        haste_settings.addWidget(self.haste_hotkey)
        haste_settings.addWidget(QLabel("Spell:"))
        self.haste_spell = QLineEdit("utani hur")
        haste_settings.addWidget(self.haste_spell)
        haste_layout.addLayout(haste_settings)

        haste_group.setLayout(haste_layout)
        scroll_layout.addWidget(haste_group)

        # Mana Training
        mana_group = QGroupBox("Mana Training")
        mana_layout = QVBoxLayout()

        self.enable_mana_training = QCheckBox("Ativar Mana Training")
        mana_layout.addWidget(self.enable_mana_training)

        mana_settings = QHBoxLayout()
        mana_settings.addWidget(QLabel("Usar quando mana >="))
        self.mana_threshold = QSpinBox()
        self.mana_threshold.setRange(10, 100)
        self.mana_threshold.setValue(90)
        self.mana_threshold.setSuffix("%")
        mana_settings.addWidget(self.mana_threshold)
        mana_settings.addWidget(QLabel("Hotkey:"))
        self.mana_hotkey = QComboBox()
        self.mana_hotkey.setEditable(True)
        self.mana_hotkey.addItems(["shift+1", "shift+2", "shift+3"])
        mana_settings.addWidget(self.mana_hotkey)
        mana_layout.addLayout(mana_settings)

        mana_group.setLayout(mana_layout)
        scroll_layout.addWidget(mana_group)

        # Anti-Paralyze
        antiparalyze_group = QGroupBox("Anti-Paralyze")
        antiparalyze_layout = QVBoxLayout()

        self.enable_antiparalyze = QCheckBox("Ativar Anti-Paralyze")
        antiparalyze_layout.addWidget(self.enable_antiparalyze)

        antiparalyze_settings = QHBoxLayout()
        antiparalyze_settings.addWidget(QLabel("Hotkey:"))
        self.antiparalyze_hotkey = QComboBox()
        self.antiparalyze_hotkey.setEditable(True)
        self.antiparalyze_hotkey.addItems(["ctrl+5", "ctrl+6", "ctrl+7"])
        antiparalyze_settings.addWidget(self.antiparalyze_hotkey)
        antiparalyze_layout.addLayout(antiparalyze_settings)

        antiparalyze_group.setLayout(antiparalyze_layout)
        scroll_layout.addWidget(antiparalyze_group)

        # Auto Eat
        eat_group = QGroupBox("Auto Eat Food")
        eat_layout = QVBoxLayout()

        self.enable_auto_eat = QCheckBox("Ativar Auto Eat")
        eat_layout.addWidget(self.enable_auto_eat)

        eat_settings = QHBoxLayout()
        eat_settings.addWidget(QLabel("Hotkey:"))
        self.eat_hotkey = QComboBox()
        self.eat_hotkey.setEditable(True)
        self.eat_hotkey.addItems(["F12", "shift+F12", "ctrl+F12"])
        eat_settings.addWidget(self.eat_hotkey)
        eat_settings.addWidget(QLabel("Intervalo (s):"))
        self.eat_interval = QSpinBox()
        self.eat_interval.setRange(30, 300)
        self.eat_interval.setValue(60)
        eat_settings.addWidget(self.eat_interval)
        eat_layout.addLayout(eat_settings)

        eat_group.setLayout(eat_layout)
        scroll_layout.addWidget(eat_group)

        # Attack/Follow Settings
        attack_group = QGroupBox("Ataque Automático")
        attack_layout = QVBoxLayout()

        self.enable_auto_attack = QCheckBox("Ativar Auto Attack")
        attack_layout.addWidget(self.enable_auto_attack)

        attack_settings = QHBoxLayout()
        attack_settings.addWidget(QLabel("Attack Hotkey:"))
        self.attack_hotkey = QComboBox()
        self.attack_hotkey.setEditable(True)
        self.attack_hotkey.addItems(["space", "ctrl+a", "alt+a"])
        attack_settings.addWidget(self.attack_hotkey)
        attack_layout.addLayout(attack_settings)

        attack_group.setLayout(attack_layout)
        scroll_layout.addWidget(attack_group)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)
        self.setLayout(layout)


class FriendHealingPanel(QWidget):
    """Painel para heal em amigos (Party Healing)"""

    def __init__(self, executor: BotExecutor):
        super().__init__()
        self.executor = executor
        self.friend_widgets: List[Dict] = []
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # Lista de amigos
        friend_list_group = QGroupBox("Lista de Amigos")
        friend_list_layout = QVBoxLayout()

        self.friend_list = QListWidget()
        friend_list_layout.addWidget(self.friend_list)

        # Botões para adicionar/remover amigos
        friend_buttons = QHBoxLayout()
        self.friend_name_input = QLineEdit()
        self.friend_name_input.setPlaceholderText("Nome do amigo...")
        friend_buttons.addWidget(self.friend_name_input)

        add_friend_btn = QPushButton("Adicionar")
        add_friend_btn.clicked.connect(self.add_friend)
        friend_buttons.addWidget(add_friend_btn)

        remove_friend_btn = QPushButton("Remover")
        remove_friend_btn.clicked.connect(self.remove_friend)
        friend_buttons.addWidget(remove_friend_btn)

        friend_list_layout.addLayout(friend_buttons)
        friend_list_group.setLayout(friend_list_layout)
        layout.addWidget(friend_list_group)

        # Friend Healing Slots
        heal_group = QGroupBox("Friend Healing Slots")
        heal_layout = QVBoxLayout()

        for i in range(1, 5):
            slot = self._create_friend_healing_slot(f"Friend Heal {i}", f"friend_{i}")
            heal_layout.addLayout(slot)

        heal_group.setLayout(heal_layout)
        layout.addWidget(heal_group)

        # Party Heal (AOE)
        party_group = QGroupBox("Party Heal (AOE)")
        party_layout = QVBoxLayout()

        self.enable_party_heal = QCheckBox("Ativar Party Heal")
        party_layout.addWidget(self.enable_party_heal)

        party_settings = QHBoxLayout()
        party_settings.addWidget(QLabel("Hotkey:"))
        self.party_heal_hotkey = QComboBox()
        self.party_heal_hotkey.setEditable(True)
        self.party_heal_hotkey.addItems(["ctrl+f1", "ctrl+f2", "ctrl+f3"])
        party_settings.addWidget(self.party_heal_hotkey)
        party_settings.addWidget(QLabel("Min. amigos com HP <"))
        self.party_min_friends = QSpinBox()
        self.party_min_friends.setRange(1, 5)
        self.party_min_friends.setValue(2)
        party_settings.addWidget(self.party_min_friends)
        party_settings.addWidget(QLabel("Threshold:"))
        self.party_threshold = QSpinBox()
        self.party_threshold.setRange(1, 100)
        self.party_threshold.setValue(70)
        self.party_threshold.setSuffix("%")
        party_settings.addWidget(self.party_threshold)
        party_layout.addLayout(party_settings)

        party_group.setLayout(party_layout)
        layout.addWidget(party_group)

        layout.addStretch()
        self.setLayout(layout)

    def _create_friend_healing_slot(self, name: str, slot_id: str) -> QHBoxLayout:
        """Cria um slot de friend healing"""
        layout = QHBoxLayout()

        enable = QCheckBox()
        enable.setObjectName(f"{slot_id}_enable")
        layout.addWidget(enable)

        label = QLabel(f"{name}:")
        label.setMinimumWidth(80)
        layout.addWidget(label)

        hotkey = QComboBox()
        hotkey.setEditable(True)
        hotkey.addItems(
            ["ctrl+f1", "ctrl+f2", "ctrl+f3", "ctrl+f4", "shift+f1", "shift+f2"]
        )
        hotkey.setObjectName(f"{slot_id}_hotkey")
        layout.addWidget(hotkey)

        threshold = QSpinBox()
        threshold.setRange(1, 100)
        threshold.setValue(60)
        threshold.setSuffix("%")
        threshold.setObjectName(f"{slot_id}_threshold")
        layout.addWidget(threshold)

        self.friend_widgets.append(
            {
                "id": slot_id,
                "enable": enable,
                "hotkey": hotkey,
                "threshold": threshold,
            }
        )

        return layout

    def add_friend(self):
        """Adiciona um amigo à lista"""
        name = self.friend_name_input.text().strip()
        if name:
            self.friend_list.addItem(name)
            self.executor.add_friend(name)
            self.friend_name_input.clear()

    def remove_friend(self):
        """Remove o amigo selecionado"""
        current = self.friend_list.currentItem()
        if current:
            name = current.text()
            self.friend_list.takeItem(self.friend_list.row(current))
            self.executor.remove_friend(name)

    def get_friend_rules(self) -> List[HealingRule]:
        """Retorna as regras de friend healing"""
        rules = []
        for i, widget in enumerate(self.friend_widgets):
            if widget["enable"].isChecked():
                rule = HealingRule(
                    name=widget["id"],
                    enabled=True,
                    hotkey=widget["hotkey"].currentText(),
                    threshold=widget["threshold"].value(),
                    condition=ConditionType.HP_BELOW,
                    target=TargetType.FRIEND,
                    priority=len(self.friend_widgets) - i,
                )
                rules.append(rule)
        return rules


class MacrosPanel(QWidget):
    """Painel para gerenciar macros customizadas"""

    def __init__(self, executor: BotExecutor):
        super().__init__()
        self.executor = executor
        self.macro_widgets: List[Dict] = []
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # Lista de macros
        macros_group = QGroupBox("Macros Ativas")
        macros_layout = QVBoxLayout()

        self.macro_list = QListWidget()
        macros_layout.addWidget(self.macro_list)

        macros_group.setLayout(macros_layout)
        layout.addWidget(macros_group)

        # Criador de macro simples
        create_group = QGroupBox("Criar Macro Simples")
        create_layout = QVBoxLayout()

        # Nome
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Nome:"))
        self.macro_name = QLineEdit()
        self.macro_name.setPlaceholderText("Nome da macro...")
        name_layout.addWidget(self.macro_name)
        create_layout.addLayout(name_layout)

        # Hotkey
        hotkey_layout = QHBoxLayout()
        hotkey_layout.addWidget(QLabel("Hotkey:"))
        self.macro_hotkey = QComboBox()
        self.macro_hotkey.setEditable(True)
        self.macro_hotkey.addItems(
            [
                "F1",
                "F2",
                "F3",
                "F4",
                "F5",
                "F6",
                "F7",
                "F8",
                "F9",
                "F10",
                "F11",
                "F12",
                "ctrl+1",
                "ctrl+2",
                "ctrl+3",
                "ctrl+4",
                "alt+1",
                "alt+2",
                "alt+3",
                "alt+4",
            ]
        )
        hotkey_layout.addWidget(self.macro_hotkey)
        create_layout.addLayout(hotkey_layout)

        # Intervalo
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("Intervalo (ms):"))
        self.macro_interval = QSpinBox()
        self.macro_interval.setRange(100, 60000)
        self.macro_interval.setValue(1000)
        interval_layout.addWidget(self.macro_interval)
        create_layout.addLayout(interval_layout)

        # Condição
        condition_layout = QHBoxLayout()
        condition_layout.addWidget(QLabel("Condição:"))
        self.macro_condition = QComboBox()
        self.macro_condition.addItems(
            [
                "Sempre",
                "HP Abaixo de",
                "HP Acima de",
                "Mana Abaixo de",
                "Mana Acima de",
                "Com Target",
                "Sem Target",
            ]
        )
        condition_layout.addWidget(self.macro_condition)
        self.macro_condition_value = QSpinBox()
        self.macro_condition_value.setRange(1, 100)
        self.macro_condition_value.setValue(50)
        self.macro_condition_value.setSuffix("%")
        condition_layout.addWidget(self.macro_condition_value)
        create_layout.addLayout(condition_layout)

        # Botões
        buttons_layout = QHBoxLayout()
        add_macro_btn = QPushButton("Adicionar Macro")
        add_macro_btn.clicked.connect(self.add_macro)
        buttons_layout.addWidget(add_macro_btn)

        remove_macro_btn = QPushButton("Remover Selecionada")
        remove_macro_btn.clicked.connect(self.remove_macro)
        buttons_layout.addWidget(remove_macro_btn)
        create_layout.addLayout(buttons_layout)

        create_group.setLayout(create_layout)
        layout.addWidget(create_group)

        layout.addStretch()
        self.setLayout(layout)

    def add_macro(self):
        """Adiciona uma nova macro"""
        name = self.macro_name.text().strip()
        if not name:
            return

        hotkey = self.macro_hotkey.currentText()
        interval = self.macro_interval.value()
        condition_text = self.macro_condition.currentText()
        condition_value = self.macro_condition_value.value()

        # Determina a condição
        condition = ConditionType.ALWAYS
        if "HP Abaixo" in condition_text:
            condition = ConditionType.HP_BELOW
        elif "HP Acima" in condition_text:
            condition = ConditionType.HP_ABOVE
        elif "Mana Abaixo" in condition_text:
            condition = ConditionType.MANA_BELOW
        elif "Mana Acima" in condition_text:
            condition = ConditionType.MANA_ABOVE
        elif "Com Target" in condition_text:
            condition = ConditionType.HAS_TARGET
        elif "Sem Target" in condition_text:
            condition = ConditionType.NO_TARGET

        # Cria callback para a macro
        def macro_callback(macro):
            executor = self.executor
            should_execute = False

            if condition == ConditionType.ALWAYS:
                should_execute = True
            elif condition == ConditionType.HP_BELOW:
                should_execute = executor.player.hp_percent < condition_value
            elif condition == ConditionType.HP_ABOVE:
                should_execute = executor.player.hp_percent > condition_value
            elif condition == ConditionType.MANA_BELOW:
                should_execute = executor.player.mana_percent < condition_value
            elif condition == ConditionType.MANA_ABOVE:
                should_execute = executor.player.mana_percent > condition_value
            elif condition == ConditionType.HAS_TARGET:
                should_execute = executor.player.has_target
            elif condition == ConditionType.NO_TARGET:
                should_execute = not executor.player.has_target

            if should_execute:
                executor.press_key(hotkey)
                return True
            return False

        # Adiciona ao executor
        macro = self.executor.add_macro(name, macro_callback, interval, hotkey)

        # Adiciona à lista visual
        item_text = f"{name} | {hotkey} | {interval}ms | {condition_text}"
        if (
            condition != ConditionType.ALWAYS
            and condition != ConditionType.HAS_TARGET
            and condition != ConditionType.NO_TARGET
        ):
            item_text += f" {condition_value}%"
        self.macro_list.addItem(item_text)

        # Limpa inputs
        self.macro_name.clear()

    def remove_macro(self):
        """Remove a macro selecionada"""
        current = self.macro_list.currentItem()
        if current:
            text = current.text()
            name = text.split(" | ")[0]
            self.executor.remove_macro(name)
            self.macro_list.takeItem(self.macro_list.row(current))


class MessagesPanel(QWidget):
    """Painel de mensagens/log do bot"""

    def __init__(self, executor: BotExecutor):
        super().__init__()
        self.executor = executor
        self.init_ui()

        # Conecta ao signal de mensagens
        self.executor.message_signal.connect(self.add_message)

    def init_ui(self):
        layout = QVBoxLayout()

        # Log de mensagens
        log_group = QGroupBox("Log do Bot")
        log_layout = QVBoxLayout()

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(200)
        log_layout.addWidget(self.log_text)

        # Botão limpar
        clear_btn = QPushButton("Limpar Log")
        clear_btn.clicked.connect(self.clear_log)
        log_layout.addWidget(clear_btn)

        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        # Status atual
        status_group = QGroupBox("Status do Jogador")
        status_layout = QGridLayout()

        status_layout.addWidget(QLabel("HP:"), 0, 0)
        self.hp_label = QLabel("0 / 0 (0%)")
        self.hp_label.setStyleSheet("color: #ff4444;")
        status_layout.addWidget(self.hp_label, 0, 1)

        status_layout.addWidget(QLabel("Mana:"), 1, 0)
        self.mana_label = QLabel("0 / 0 (0%)")
        self.mana_label.setStyleSheet("color: #4444ff;")
        status_layout.addWidget(self.mana_label, 1, 1)

        status_layout.addWidget(QLabel("Target:"), 2, 0)
        self.target_label = QLabel("Nenhum")
        status_layout.addWidget(self.target_label, 2, 1)

        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        # Estatísticas
        stats_group = QGroupBox("Estatísticas")
        stats_layout = QGridLayout()

        stats_layout.addWidget(QLabel("Heals usados:"), 0, 0)
        self.heals_label = QLabel("0")
        stats_layout.addWidget(self.heals_label, 0, 1)

        stats_layout.addWidget(QLabel("Macros executadas:"), 1, 0)
        self.macros_label = QLabel("0")
        stats_layout.addWidget(self.macros_label, 1, 1)

        stats_layout.addWidget(QLabel("Tempo ativo:"), 2, 0)
        self.time_label = QLabel("00:00:00")
        stats_layout.addWidget(self.time_label, 2, 1)

        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)

        layout.addStretch()
        self.setLayout(layout)

    def add_message(self, category: str, text: str):
        """Adiciona mensagem ao log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        color = "white"
        if category == "error":
            color = "#ff4444"
        elif category == "warn":
            color = "#ffaa00"
        elif category == "info":
            color = "#44ff44"

        html = f'<span style="color: gray;">[{timestamp}]</span> <span style="color: {color};">{text}</span>'
        self.log_text.append(html)

        # Auto-scroll para o final
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def clear_log(self):
        """Limpa o log"""
        self.log_text.clear()

    def update_status(self, player: PlayerState):
        """Atualiza o status do jogador"""
        self.hp_label.setText(
            f"{player.hp} / {player.hp_max} ({player.hp_percent:.1f}%)"
        )
        self.mana_label.setText(
            f"{player.mana} / {player.mana_max} ({player.mana_percent:.1f}%)"
        )
        self.target_label.setText("Sim" if player.has_target else "Nenhum")


class CaveBotPanel(QWidget):
    """Painel do CaveBot com waypoints"""

    def __init__(self, executor: BotExecutor):
        super().__init__()
        self.executor = executor
        self.recording = False
        self.record_hotkey = "ctrl+w"
        self.init_ui()
        self._setup_hotkeys()

    def init_ui(self):
        layout = QVBoxLayout()

        # Controles principais
        control_group = QGroupBox("Controles do CaveBot")
        control_layout = QVBoxLayout()

        # Botões de controle
        buttons_layout = QHBoxLayout()

        self.enable_btn = QPushButton("▶ Ativar")
        self.enable_btn.setCheckable(True)
        self.enable_btn.clicked.connect(self.toggle_cavebot)
        self.enable_btn.setStyleSheet("""
            QPushButton { background-color: #4CAF50; color: white; padding: 8px; font-weight: bold; }
            QPushButton:checked { background-color: #f44336; }
        """)
        buttons_layout.addWidget(self.enable_btn)

        self.pause_btn = QPushButton("⏸ Pausar")
        self.pause_btn.setCheckable(True)
        self.pause_btn.clicked.connect(self.toggle_pause)
        buttons_layout.addWidget(self.pause_btn)

        self.record_btn = QPushButton("⏺ Gravar (Ctrl+W)")
        self.record_btn.setCheckable(True)
        self.record_btn.clicked.connect(self.toggle_recording)
        self.record_btn.setStyleSheet("""
            QPushButton { background-color: #2196F3; color: white; padding: 8px; }
            QPushButton:checked { background-color: #ff5722; }
        """)
        buttons_layout.addWidget(self.record_btn)

        control_layout.addLayout(buttons_layout)

        # Status
        status_layout = QHBoxLayout()
        status_layout.addWidget(QLabel("Status:"))
        self.status_label = QLabel("Desativado")
        self.status_label.setStyleSheet("color: #ff4444; font-weight: bold;")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        status_layout.addWidget(QLabel("Waypoint:"))
        self.wp_index_label = QLabel("0 / 0")
        status_layout.addWidget(self.wp_index_label)
        control_layout.addLayout(status_layout)

        # Delay de movimento
        delay_layout = QHBoxLayout()
        delay_layout.addWidget(QLabel("Delay entre movimentos (ms):"))
        self.move_delay_spin = QSpinBox()
        self.move_delay_spin.setRange(50, 2000)
        self.move_delay_spin.setValue(200)
        self.move_delay_spin.valueChanged.connect(self.update_delay)
        delay_layout.addWidget(self.move_delay_spin)
        control_layout.addLayout(delay_layout)

        control_group.setLayout(control_layout)
        layout.addWidget(control_group)

        # Posição atual
        pos_group = QGroupBox("Posição Atual do Player")
        pos_layout = QHBoxLayout()

        pos_layout.addWidget(QLabel("X:"))
        self.pos_x = QSpinBox()
        self.pos_x.setRange(-100000, 100000)
        pos_layout.addWidget(self.pos_x)

        pos_layout.addWidget(QLabel("Y:"))
        self.pos_y = QSpinBox()
        self.pos_y.setRange(-100000, 100000)
        pos_layout.addWidget(self.pos_y)

        pos_layout.addWidget(QLabel("Z:"))
        self.pos_z = QSpinBox()
        self.pos_z.setRange(0, 15)
        pos_layout.addWidget(self.pos_z)

        add_pos_btn = QPushButton("+ Adicionar")
        add_pos_btn.clicked.connect(self.add_current_position)
        pos_layout.addWidget(add_pos_btn)

        pos_group.setLayout(pos_layout)
        layout.addWidget(pos_group)

        # Lista de waypoints
        wp_group = QGroupBox("Waypoints")
        wp_layout = QVBoxLayout()

        self.waypoint_list = QListWidget()
        self.waypoint_list.setMinimumHeight(200)
        wp_layout.addWidget(self.waypoint_list)

        # Tipo de waypoint para adicionar
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Tipo:"))
        self.wp_type_combo = QComboBox()
        self.wp_type_combo.addItems(
            [
                "WALK - Andar",
                "ROPE - Usar Rope",
                "SHOVEL - Usar Shovel",
                "LADDER - Subir Escada",
                "STAND - Esperar",
                "ACTION - Executar Hotkey",
                "LABEL - Marcador",
            ]
        )
        type_layout.addWidget(self.wp_type_combo)

        type_layout.addWidget(QLabel("Ação/Label:"))
        self.wp_action_input = QLineEdit()
        self.wp_action_input.setPlaceholderText("Hotkey ou nome do label...")
        type_layout.addWidget(self.wp_action_input)

        wp_layout.addLayout(type_layout)

        # Botões de edição
        edit_buttons = QHBoxLayout()

        remove_btn = QPushButton("🗑 Remover")
        remove_btn.clicked.connect(self.remove_selected)
        edit_buttons.addWidget(remove_btn)

        clear_btn = QPushButton("🧹 Limpar Tudo")
        clear_btn.clicked.connect(self.clear_all)
        edit_buttons.addWidget(clear_btn)

        move_up_btn = QPushButton("⬆ Subir")
        move_up_btn.clicked.connect(self.move_up)
        edit_buttons.addWidget(move_up_btn)

        move_down_btn = QPushButton("⬇ Descer")
        move_down_btn.clicked.connect(self.move_down)
        edit_buttons.addWidget(move_down_btn)

        wp_layout.addLayout(edit_buttons)

        wp_group.setLayout(wp_layout)
        layout.addWidget(wp_group)

        # Salvar/Carregar
        file_group = QGroupBox("Salvar/Carregar Waypoints")
        file_layout = QHBoxLayout()

        save_btn = QPushButton("💾 Salvar")
        save_btn.clicked.connect(self.save_waypoints)
        file_layout.addWidget(save_btn)

        load_btn = QPushButton("📂 Carregar")
        load_btn.clicked.connect(self.load_waypoints)
        file_layout.addWidget(load_btn)

        file_group.setLayout(file_layout)
        layout.addWidget(file_group)

        # Configuração de leitura de posição
        pos_config_group = QGroupBox("Leitura de Posição (Integração OTClient)")
        pos_config_layout = QVBoxLayout()

        # Método de leitura
        method_layout = QHBoxLayout()
        method_layout.addWidget(QLabel("Método:"))
        self.pos_method_combo = QComboBox()
        self.pos_method_combo.addItems(["Manual", "Arquivo JSON", "HTTP API"])
        self.pos_method_combo.currentIndexChanged.connect(self.change_position_method)
        method_layout.addWidget(self.pos_method_combo)
        pos_config_layout.addLayout(method_layout)

        # Arquivo de posição
        file_pos_layout = QHBoxLayout()
        file_pos_layout.addWidget(QLabel("Arquivo:"))
        self.pos_file_input = QLineEdit("player_position.json")
        file_pos_layout.addWidget(self.pos_file_input)
        browse_pos_btn = QPushButton("📂")
        browse_pos_btn.setMaximumWidth(40)
        browse_pos_btn.clicked.connect(self.browse_position_file)
        file_pos_layout.addWidget(browse_pos_btn)
        pos_config_layout.addLayout(file_pos_layout)

        # URL HTTP
        http_layout = QHBoxLayout()
        http_layout.addWidget(QLabel("URL HTTP:"))
        self.http_url_input = QLineEdit("http://localhost:8080/position")
        http_layout.addWidget(self.http_url_input)
        pos_config_layout.addLayout(http_layout)

        # Botão para iniciar monitoramento
        monitor_layout = QHBoxLayout()
        self.start_monitor_btn = QPushButton("▶ Iniciar Monitoramento")
        self.start_monitor_btn.clicked.connect(self.toggle_position_monitor)
        monitor_layout.addWidget(self.start_monitor_btn)
        pos_config_layout.addLayout(monitor_layout)

        # Info
        info_label = QLabel(
            "💡 Dica: Configure o OTClient para exportar posição em JSON\n"
            "   ou use o módulo HTTP para comunicação em tempo real."
        )
        info_label.setStyleSheet("color: #888888; font-size: 11px;")
        pos_config_layout.addWidget(info_label)

        pos_config_group.setLayout(pos_config_layout)
        layout.addWidget(pos_config_group)

        layout.addStretch()
        self.setLayout(layout)

    def change_position_method(self, index):
        """Muda o método de leitura de posição"""
        methods = ["manual", "file", "http"]
        self.executor.position_reader.method = methods[index]
        self.executor.info(f"Método de posição: {methods[index]}")

    def browse_position_file(self):
        """Abre diálogo para selecionar arquivo de posição"""
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar Arquivo de Posição",
            "",
            "JSON Files (*.json);;All Files (*)",
        )
        if filepath:
            self.pos_file_input.setText(filepath)
            self.executor.position_reader.position_file = filepath

    def toggle_position_monitor(self):
        """Inicia/para monitoramento de arquivo"""
        if self.executor.position_reader._observer is None:
            filepath = self.pos_file_input.text()
            if (
                os.path.exists(filepath)
                or self.executor.position_reader.method == "file"
            ):
                self.executor.position_reader.position_file = filepath
                self.executor.position_reader.start_file_watcher(filepath)
                self.start_monitor_btn.setText("⏹ Parar Monitoramento")
            else:
                self.executor.warn(f"Arquivo não encontrado: {filepath}")
        else:
            self.executor.position_reader.stop_file_watcher()
            self.start_monitor_btn.setText("▶ Iniciar Monitoramento")

    def _setup_hotkeys(self):
        """Configura hotkeys para gravação"""
        try:
            keyboard.add_hotkey(self.record_hotkey, self.record_current_position)
        except Exception as e:
            print(f"Erro ao configurar hotkey: {e}")

    def toggle_cavebot(self, checked):
        """Ativa/desativa o cavebot"""
        self.executor.cavebot.enabled = checked
        if checked:
            self.enable_btn.setText("⏹ Desativar")
            self.status_label.setText("Ativo")
            self.status_label.setStyleSheet("color: #44ff44; font-weight: bold;")
        else:
            self.enable_btn.setText("▶ Ativar")
            self.status_label.setText("Desativado")
            self.status_label.setStyleSheet("color: #ff4444; font-weight: bold;")

    def toggle_pause(self, checked):
        """Pausa/continua o cavebot"""
        self.executor.cavebot.paused = checked
        if checked:
            self.pause_btn.setText("▶ Continuar")
            self.status_label.setText("Pausado")
            self.status_label.setStyleSheet("color: #ffaa00; font-weight: bold;")
        else:
            self.pause_btn.setText("⏸ Pausar")
            if self.executor.cavebot.enabled:
                self.status_label.setText("Ativo")
                self.status_label.setStyleSheet("color: #44ff44; font-weight: bold;")

    def toggle_recording(self, checked):
        """Ativa/desativa o modo de gravação"""
        self.recording = checked
        if checked:
            self.record_btn.setText("⏹ Parar Gravação")
            self.executor.info(
                "Modo de gravação ativado! Use Ctrl+W para gravar posição."
            )
        else:
            self.record_btn.setText("⏺ Gravar (Ctrl+W)")
            self.executor.info("Modo de gravação desativado.")

    def record_current_position(self):
        """Grava a posição atual como waypoint (chamado via hotkey)"""
        if not self.recording:
            return

        pos = self.executor.player.position
        wp_type = self._get_selected_type()
        action = self.wp_action_input.text().strip()

        waypoint = Waypoint(
            x=pos[0],
            y=pos[1],
            z=pos[2],
            waypoint_type=wp_type,
            action=action if wp_type == WaypointType.ACTION else "",
            label=action if wp_type == WaypointType.LABEL else "",
        )

        self.executor.cavebot.add_waypoint(waypoint)
        self._refresh_list()
        self.executor.info(f"Waypoint gravado: {waypoint}")

    def add_current_position(self):
        """Adiciona a posição dos spinboxes como waypoint"""
        wp_type = self._get_selected_type()
        action = self.wp_action_input.text().strip()

        waypoint = Waypoint(
            x=self.pos_x.value(),
            y=self.pos_y.value(),
            z=self.pos_z.value(),
            waypoint_type=wp_type,
            action=action if wp_type == WaypointType.ACTION else "",
            label=action if wp_type == WaypointType.LABEL else "",
        )

        self.executor.cavebot.add_waypoint(waypoint)
        self._refresh_list()
        self.executor.info(f"Waypoint adicionado: {waypoint}")

    def _get_selected_type(self) -> WaypointType:
        """Retorna o tipo de waypoint selecionado"""
        text = self.wp_type_combo.currentText()
        if "ROPE" in text:
            return WaypointType.ROPE
        elif "SHOVEL" in text:
            return WaypointType.SHOVEL
        elif "LADDER" in text:
            return WaypointType.LADDER
        elif "STAND" in text:
            return WaypointType.STAND
        elif "ACTION" in text:
            return WaypointType.ACTION
        elif "LABEL" in text:
            return WaypointType.LABEL
        return WaypointType.WALK

    def remove_selected(self):
        """Remove o waypoint selecionado"""
        current = self.waypoint_list.currentRow()
        if current >= 0:
            self.executor.cavebot.remove_waypoint(current)
            self._refresh_list()

    def clear_all(self):
        """Limpa todos os waypoints"""
        reply = QMessageBox.question(
            self,
            "Confirmar",
            "Tem certeza que deseja limpar todos os waypoints?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.executor.cavebot.clear_waypoints()
            self._refresh_list()

    def move_up(self):
        """Move o waypoint selecionado para cima"""
        current = self.waypoint_list.currentRow()
        if current > 0:
            wp = self.executor.cavebot.waypoints.pop(current)
            self.executor.cavebot.waypoints.insert(current - 1, wp)
            self.executor.cavebot._rebuild_labels()
            self._refresh_list()
            self.waypoint_list.setCurrentRow(current - 1)

    def move_down(self):
        """Move o waypoint selecionado para baixo"""
        current = self.waypoint_list.currentRow()
        if current >= 0 and current < len(self.executor.cavebot.waypoints) - 1:
            wp = self.executor.cavebot.waypoints.pop(current)
            self.executor.cavebot.waypoints.insert(current + 1, wp)
            self.executor.cavebot._rebuild_labels()
            self._refresh_list()
            self.waypoint_list.setCurrentRow(current + 1)

    def update_delay(self, value):
        """Atualiza o delay de movimento"""
        self.executor.cavebot.move_delay = value

    def _refresh_list(self):
        """Atualiza a lista de waypoints na UI"""
        self.waypoint_list.clear()
        for i, wp in enumerate(self.executor.cavebot.waypoints):
            item = QListWidgetItem(f"{i + 1}. {wp}")
            self.waypoint_list.addItem(item)
        self.wp_index_label.setText(
            f"{self.executor.cavebot.current_index + 1} / {len(self.executor.cavebot.waypoints)}"
        )

    def save_waypoints(self):
        """Salva waypoints em arquivo"""
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Salvar Waypoints", "", "JSON Files (*.json)"
        )
        if filepath:
            if not filepath.endswith(".json"):
                filepath += ".json"
            self.executor.cavebot.save_waypoints(filepath)
            self.executor.info(f"Waypoints salvos em: {filepath}")

    def load_waypoints(self):
        """Carrega waypoints de arquivo"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Carregar Waypoints", "", "JSON Files (*.json)"
        )
        if filepath:
            try:
                self.executor.cavebot.load_waypoints(filepath)
                self._refresh_list()
                self.executor.info(f"Waypoints carregados de: {filepath}")
            except Exception as e:
                self.executor.error(f"Erro ao carregar waypoints: {e}")

    def update_position_display(self):
        """Atualiza a exibição da posição atual"""
        pos = self.executor.player.position
        self.pos_x.setValue(pos[0])
        self.pos_y.setValue(pos[1])
        self.pos_z.setValue(pos[2])
        self.wp_index_label.setText(
            f"{self.executor.cavebot.current_index + 1} / {len(self.executor.cavebot.waypoints)}"
        )


class MacroRecorderPanel(QWidget):
    """Painel para gravar e reproduzir macros de teclado/mouse"""

    def __init__(self, executor: BotExecutor):
        super().__init__()
        self.executor = executor
        self.recorder = MacroRecorder()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # Controles principais
        control_group = QGroupBox("Controles de Gravação")
        control_layout = QVBoxLayout()

        # Botões principais
        buttons_layout = QHBoxLayout()

        self.record_btn = QPushButton("⏺ Gravar (F6)")
        self.record_btn.setCheckable(True)
        self.record_btn.clicked.connect(self.toggle_recording)
        self.record_btn.setStyleSheet("""
            QPushButton { background-color: #4CAF50; color: white; padding: 10px; font-weight: bold; }
            QPushButton:checked { background-color: #f44336; }
        """)
        buttons_layout.addWidget(self.record_btn)

        self.play_btn = QPushButton("▶ Reproduzir (F7)")
        self.play_btn.clicked.connect(self.toggle_playback)
        self.play_btn.setStyleSheet("""
            QPushButton { background-color: #2196F3; color: white; padding: 10px; font-weight: bold; }
        """)
        buttons_layout.addWidget(self.play_btn)

        self.stop_btn = QPushButton("⏹ Parar")
        self.stop_btn.clicked.connect(self.stop_all)
        buttons_layout.addWidget(self.stop_btn)

        control_layout.addLayout(buttons_layout)

        # Status
        status_layout = QHBoxLayout()
        status_layout.addWidget(QLabel("Status:"))
        self.status_label = QLabel("Parado")
        self.status_label.setStyleSheet("font-weight: bold;")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        status_layout.addWidget(QLabel("Eventos:"))
        self.event_count_label = QLabel("0")
        status_layout.addWidget(self.event_count_label)
        control_layout.addLayout(status_layout)

        control_group.setLayout(control_layout)
        layout.addWidget(control_group)

        # Configurações
        config_group = QGroupBox("Configurações de Gravação")
        config_layout = QVBoxLayout()

        self.record_keys_cb = QCheckBox("Gravar teclas")
        self.record_keys_cb.setChecked(True)
        self.record_keys_cb.stateChanged.connect(self.update_config)
        config_layout.addWidget(self.record_keys_cb)

        self.record_clicks_cb = QCheckBox("Gravar cliques do mouse")
        self.record_clicks_cb.setChecked(True)
        self.record_clicks_cb.stateChanged.connect(self.update_config)
        config_layout.addWidget(self.record_clicks_cb)

        self.record_moves_cb = QCheckBox(
            "Gravar movimentos do mouse (gera muitos eventos)"
        )
        self.record_moves_cb.setChecked(False)
        self.record_moves_cb.stateChanged.connect(self.update_config)
        config_layout.addWidget(self.record_moves_cb)

        # Loop
        self.loop_cb = QCheckBox("Repetir em loop")
        self.loop_cb.setChecked(False)
        config_layout.addWidget(self.loop_cb)

        # Seleção de janela
        window_layout = QHBoxLayout()
        window_layout.addWidget(QLabel("Janela alvo:"))
        self.window_combo = QComboBox()
        self.window_combo.setMinimumWidth(200)
        window_layout.addWidget(self.window_combo)
        refresh_windows_btn = QPushButton("🔄")
        refresh_windows_btn.setMaximumWidth(40)
        refresh_windows_btn.clicked.connect(self.refresh_windows)
        window_layout.addWidget(refresh_windows_btn)
        config_layout.addLayout(window_layout)

        # Popula lista de janelas
        self.refresh_windows()

        # Velocidade
        speed_layout = QHBoxLayout()
        speed_layout.addWidget(QLabel("Velocidade:"))
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(25, 400)
        self.speed_slider.setValue(100)
        self.speed_slider.valueChanged.connect(self.update_speed)
        speed_layout.addWidget(self.speed_slider)
        self.speed_label = QLabel("1.0x")
        speed_layout.addWidget(self.speed_label)
        config_layout.addLayout(speed_layout)

        config_group.setLayout(config_layout)
        layout.addWidget(config_group)

        # Lista de eventos
        events_group = QGroupBox("Eventos Gravados")
        events_layout = QVBoxLayout()

        self.events_list = QListWidget()
        self.events_list.setMaximumHeight(200)
        events_layout.addWidget(self.events_list)

        # Botões da lista
        list_buttons = QHBoxLayout()
        clear_btn = QPushButton("🗑 Limpar")
        clear_btn.clicked.connect(self.clear_events)
        list_buttons.addWidget(clear_btn)

        remove_btn = QPushButton("✕ Remover Selecionado")
        remove_btn.clicked.connect(self.remove_selected)
        list_buttons.addWidget(remove_btn)

        events_layout.addLayout(list_buttons)
        events_group.setLayout(events_layout)
        layout.addWidget(events_group)

        # Salvar/Carregar
        file_group = QGroupBox("Salvar/Carregar Macro")
        file_layout = QHBoxLayout()

        save_btn = QPushButton("💾 Salvar")
        save_btn.clicked.connect(self.save_macro)
        file_layout.addWidget(save_btn)

        load_btn = QPushButton("📂 Carregar")
        load_btn.clicked.connect(self.load_macro)
        file_layout.addWidget(load_btn)

        file_group.setLayout(file_layout)
        layout.addWidget(file_group)

        # Dicas
        tips_label = QLabel(
            "💡 Dicas:\n"
            "• F6 = Iniciar/Parar gravação\n"
            "• F7 = Reproduzir macro\n"
            "• A macro grava tudo: teclas de movimento, ações, cliques\n"
            "• Selecione a janela do OTClient antes de reproduzir"
        )
        tips_label.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(tips_label)

        layout.addStretch()
        self.setLayout(layout)

        # Configura hotkeys globais
        self._setup_hotkeys()

        # Timer para atualizar UI
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_ui)
        self.update_timer.start(100)

    def _setup_hotkeys(self):
        """Configura hotkeys globais"""
        try:
            keyboard.add_hotkey("f6", self.toggle_recording_hotkey)
            keyboard.add_hotkey("f7", self.toggle_playback_hotkey)
        except Exception as e:
            print(f"Erro ao configurar hotkeys: {e}")

    def refresh_windows(self):
        """Atualiza lista de janelas disponíveis"""
        self.window_combo.clear()
        self.window_combo.addItem("(Detectar automaticamente)")

        try:

            def enum_callback(hwnd, windows):
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if title and len(title) > 0:
                        windows.append((hwnd, title))
                return True

            windows = []
            win32gui.EnumWindows(enum_callback, windows)

            # Filtra janelas relevantes
            for hwnd, title in windows:
                if any(
                    x in title.lower()
                    for x in ["otclient", "tibia", "client", "everleaf"]
                ):
                    self.window_combo.addItem(f"{title}", hwnd)

            # Adiciona separador e outras janelas
            self.window_combo.addItem("--- Outras janelas ---", None)
            for hwnd, title in windows[:30]:  # Limita a 30
                if not any(
                    x in title.lower()
                    for x in ["otclient", "tibia", "client", "everleaf"]
                ):
                    self.window_combo.addItem(f"{title[:50]}", hwnd)
        except Exception as e:
            print(f"Erro ao listar janelas: {e}")

    def get_selected_window(self):
        """Retorna a janela selecionada"""
        idx = self.window_combo.currentIndex()
        if idx > 0:
            hwnd = self.window_combo.itemData(idx)
            if hwnd:
                self.recorder.target_window = hwnd
                self.recorder.target_window_title = self.window_combo.currentText()
                return hwnd
        return None

    def toggle_recording_hotkey(self):
        """Chamado via hotkey F6"""
        self.record_btn.click()

    def toggle_playback_hotkey(self):
        """Chamado via hotkey F7"""
        if not self.recorder.recording:
            self.play_btn.click()

    def toggle_recording(self, checked):
        """Inicia/para gravação"""
        if checked:
            self.recorder.start_recording()
            self.record_btn.setText("⏹ Parar Gravação (F6)")
            self.status_label.setText("Gravando...")
            self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
            self.executor.info("Gravação de macro iniciada!")
        else:
            self.recorder.stop_recording()
            self.record_btn.setText("⏺ Gravar (F6)")
            self.status_label.setText("Parado")
            self.status_label.setStyleSheet("color: white; font-weight: bold;")
            self._refresh_events_list()
            self.executor.info(f"Gravação parada! {len(self.recorder.events)} eventos.")

    def toggle_playback(self):
        """Inicia/para reprodução"""
        if self.recorder.playing:
            self.recorder.stop_playback()
            self.play_btn.setText("▶ Reproduzir (F7)")
            self.status_label.setText("Parado")
            self.status_label.setStyleSheet("color: white; font-weight: bold;")
        else:
            if not self.recorder.events:
                self.executor.warn("Nenhum evento gravado!")
                return

            # Configura janela alvo
            self.get_selected_window()

            self.recorder.loop = self.loop_cb.isChecked()
            self.recorder.play(loop=self.loop_cb.isChecked())
            self.play_btn.setText("⏹ Parar (F7)")
            self.status_label.setText("Reproduzindo...")
            self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")

            window_info = self.recorder.target_window_title or "Auto-detectada"
            self.executor.info(f"Reproduzindo macro... (Janela: {window_info})")

    def stop_all(self):
        """Para tudo"""
        if self.recorder.recording:
            self.recorder.stop_recording()
            self.record_btn.setChecked(False)
            self.record_btn.setText("⏺ Gravar (F6)")

        if self.recorder.playing:
            self.recorder.stop_playback()
            self.play_btn.setText("▶ Reproduzir (F7)")

        self.status_label.setText("Parado")
        self.status_label.setStyleSheet("color: white; font-weight: bold;")
        self._refresh_events_list()

    def update_config(self):
        """Atualiza configurações do recorder"""
        self.recorder.record_keys = self.record_keys_cb.isChecked()
        self.recorder.record_clicks = self.record_clicks_cb.isChecked()
        self.recorder.record_mouse_move = self.record_moves_cb.isChecked()

    def update_speed(self, value):
        """Atualiza velocidade de reprodução"""
        speed = value / 100
        self.recorder.speed = speed
        self.speed_label.setText(f"{speed:.1f}x")

    def update_ui(self):
        """Atualiza UI periodicamente"""
        self.event_count_label.setText(str(len(self.recorder.events)))

        if self.recorder.playing and not self.recorder._stop_playback:
            pass  # Mantém status de reproduzindo
        elif not self.recorder.recording and not self.recorder.playing:
            if self.play_btn.text() != "▶ Reproduzir (F7)":
                self.play_btn.setText("▶ Reproduzir (F7)")
                self.status_label.setText("Parado")
                self.status_label.setStyleSheet("color: white; font-weight: bold;")

    def _refresh_events_list(self):
        """Atualiza lista de eventos na UI"""
        self.events_list.clear()
        for i, event in enumerate(
            self.recorder.events[:100]
        ):  # Limita a 100 para performance
            self.events_list.addItem(f"{i + 1}. {event}")

        if len(self.recorder.events) > 100:
            self.events_list.addItem(
                f"... e mais {len(self.recorder.events) - 100} eventos"
            )

    def clear_events(self):
        """Limpa eventos"""
        self.recorder.clear()
        self._refresh_events_list()
        self.executor.info("Eventos limpos!")

    def remove_selected(self):
        """Remove evento selecionado"""
        current = self.events_list.currentRow()
        if 0 <= current < len(self.recorder.events):
            self.recorder.events.pop(current)
            self._refresh_events_list()

    def save_macro(self):
        """Salva macro em arquivo"""
        if not self.recorder.events:
            self.executor.warn("Nenhum evento para salvar!")
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self, "Salvar Macro", "", "JSON Files (*.json)"
        )
        if filepath:
            if not filepath.endswith(".json"):
                filepath += ".json"
            self.recorder.save(filepath)
            self.executor.info(f"Macro salva: {filepath}")

    def load_macro(self):
        """Carrega macro de arquivo"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Carregar Macro", "", "JSON Files (*.json)"
        )
        if filepath:
            try:
                self.recorder.load(filepath)
                self._refresh_events_list()
                self.executor.info(
                    f"Macro carregada: {len(self.recorder.events)} eventos"
                )
            except Exception as e:
                self.executor.error(f"Erro ao carregar: {e}")


class SettingsPanel(QWidget):
    """Painel de configurações gerais"""

    def __init__(self, executor: BotExecutor):
        super().__init__()
        self.executor = executor
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # Configurações do Bot
        bot_group = QGroupBox("Configurações do Bot")
        bot_layout = QVBoxLayout()

        # Intervalo de verificação
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("Intervalo de verificação (ms):"))
        self.check_interval = QSpinBox()
        self.check_interval.setRange(10, 1000)
        self.check_interval.setValue(50)
        interval_layout.addWidget(self.check_interval)
        bot_layout.addLayout(interval_layout)

        # Perfil
        profile_layout = QHBoxLayout()
        profile_layout.addWidget(QLabel("Perfil:"))
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(["default", "hunt", "pvp", "train"])
        self.profile_combo.setEditable(True)
        profile_layout.addWidget(self.profile_combo)

        save_profile_btn = QPushButton("Salvar Perfil")
        save_profile_btn.clicked.connect(self.save_profile)
        profile_layout.addWidget(save_profile_btn)

        load_profile_btn = QPushButton("Carregar Perfil")
        load_profile_btn.clicked.connect(self.load_profile)
        profile_layout.addWidget(load_profile_btn)

        bot_layout.addLayout(profile_layout)

        bot_group.setLayout(bot_layout)
        layout.addWidget(bot_group)

        # Hotkeys Globais
        hotkey_group = QGroupBox("Hotkeys Globais")
        hotkey_layout = QVBoxLayout()

        start_stop_layout = QHBoxLayout()
        start_stop_layout.addWidget(QLabel("Iniciar/Parar Bot:"))
        self.start_stop_hotkey = QLineEdit("F8")
        self.start_stop_hotkey.setMaximumWidth(100)
        start_stop_layout.addWidget(self.start_stop_hotkey)
        start_stop_layout.addStretch()
        hotkey_layout.addLayout(start_stop_layout)

        pause_layout = QHBoxLayout()
        pause_layout.addWidget(QLabel("Pausar Bot:"))
        self.pause_hotkey = QLineEdit("F9")
        self.pause_hotkey.setMaximumWidth(100)
        pause_layout.addWidget(self.pause_hotkey)
        pause_layout.addStretch()
        hotkey_layout.addLayout(pause_layout)

        hotkey_group.setLayout(hotkey_layout)
        layout.addWidget(hotkey_group)

        # Modo de Input
        input_group = QGroupBox("Simulação de HP/Mana (Para Teste)")
        input_layout = QVBoxLayout()

        hp_layout = QHBoxLayout()
        hp_layout.addWidget(QLabel("HP %:"))
        self.test_hp = QSlider(Qt.Orientation.Horizontal)
        self.test_hp.setRange(0, 100)
        self.test_hp.setValue(100)
        self.test_hp.valueChanged.connect(self.update_test_hp)
        hp_layout.addWidget(self.test_hp)
        self.test_hp_label = QLabel("100%")
        hp_layout.addWidget(self.test_hp_label)
        input_layout.addLayout(hp_layout)

        mana_layout = QHBoxLayout()
        mana_layout.addWidget(QLabel("Mana %:"))
        self.test_mana = QSlider(Qt.Orientation.Horizontal)
        self.test_mana.setRange(0, 100)
        self.test_mana.setValue(100)
        self.test_mana.valueChanged.connect(self.update_test_mana)
        mana_layout.addWidget(self.test_mana)
        self.test_mana_label = QLabel("100%")
        mana_layout.addWidget(self.test_mana_label)
        input_layout.addLayout(mana_layout)

        self.test_target = QCheckBox("Simular Target")
        self.test_target.stateChanged.connect(self.update_test_target)
        input_layout.addWidget(self.test_target)

        input_group.setLayout(input_layout)
        layout.addWidget(input_group)

        layout.addStretch()
        self.setLayout(layout)

    def save_profile(self):
        """Salva o perfil atual"""
        profile = self.profile_combo.currentText()
        self.executor.storage.load(profile)
        # TODO: Coletar todas as configurações e salvar
        self.executor.storage.save()
        self.executor.info(f"Perfil '{profile}' salvo!")

    def load_profile(self):
        """Carrega um perfil"""
        profile = self.profile_combo.currentText()
        self.executor.storage.load(profile)
        # TODO: Aplicar configurações carregadas
        self.executor.info(f"Perfil '{profile}' carregado!")

    def update_test_hp(self, value):
        """Atualiza HP de teste"""
        self.test_hp_label.setText(f"{value}%")
        self.executor.update_player_hp(value, 100)

    def update_test_mana(self, value):
        """Atualiza Mana de teste"""
        self.test_mana_label.setText(f"{value}%")
        self.executor.update_player_mana(value, 100)

    def update_test_target(self, state):
        """Atualiza target de teste"""
        self.executor.player.has_target = state == Qt.CheckState.Checked.value


class MainWindow(QMainWindow):
    """Janela principal do bot"""

    def __init__(self):
        super().__init__()
        self.executor = BotExecutor()
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_bot)
        self.start_time = None
        self.stats = {"heals": 0, "macros": 0}
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("OTClient Bot - Python Edition")
        self.setGeometry(100, 100, 600, 700)
        self.setMinimumSize(500, 500)

        # Widget central
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Layout principal
        main_layout = QVBoxLayout()

        # Header com status
        header_layout = QHBoxLayout()

        self.status_label = QLabel("Status: Desativado")
        self.status_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        header_layout.addWidget(self.status_label)

        self.status_indicator = QLabel("●")
        self.status_indicator.setStyleSheet("color: #ff4444; font-size: 24px;")
        header_layout.addWidget(self.status_indicator)

        header_layout.addStretch()

        # Botão de minimizar
        self.minimize_button = QPushButton("─")
        self.minimize_button.setMaximumWidth(30)
        self.minimize_button.clicked.connect(self.showMinimized)
        header_layout.addWidget(self.minimize_button)

        main_layout.addLayout(header_layout)

        # Tabs
        self.tabs = QTabWidget()

        # Healing Tab
        self.healing_panel = HealingPanel(self.executor)
        self.tabs.addTab(self.healing_panel, "🩹 Healing")

        # Friend Healing Tab
        self.friend_panel = FriendHealingPanel(self.executor)
        self.tabs.addTab(self.friend_panel, "👥 Party Heal")

        # Tools Tab
        self.tools_panel = ToolsPanel(self.executor)
        self.tabs.addTab(self.tools_panel, "🔧 Tools")

        # Macros Tab
        self.macros_panel = MacrosPanel(self.executor)
        self.tabs.addTab(self.macros_panel, "⚡ Macros")

        # CaveBot Tab
        self.cavebot_panel = CaveBotPanel(self.executor)
        self.tabs.addTab(self.cavebot_panel, "🗺️ CaveBot")

        # Macro Recorder Tab
        self.macro_recorder_panel = MacroRecorderPanel(self.executor)
        self.tabs.addTab(self.macro_recorder_panel, "🎬 Macro Recorder")

        # Messages Tab
        self.messages_panel = MessagesPanel(self.executor)
        self.tabs.addTab(self.messages_panel, "📝 Log")

        # Settings Tab
        self.settings_panel = SettingsPanel(self.executor)
        self.tabs.addTab(self.settings_panel, "⚙️ Settings")

        main_layout.addWidget(self.tabs)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        main_layout.addWidget(line)

        # Botões de controle
        button_layout = QHBoxLayout()

        self.start_button = QPushButton("▶ Iniciar Bot")
        self.start_button.clicked.connect(self.toggle_bot)
        self.start_button.setStyleSheet(
            """
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 12px 24px;
                font-weight: bold;
                font-size: 14px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """
        )
        button_layout.addWidget(self.start_button)

        self.reload_button = QPushButton("🔄 Recarregar")
        self.reload_button.clicked.connect(self.reload_config)
        self.reload_button.setStyleSheet(
            """
            QPushButton {
                background-color: #2196F3;
                color: white;
                padding: 12px 24px;
                font-weight: bold;
                font-size: 14px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """
        )
        button_layout.addWidget(self.reload_button)

        self.close_button = QPushButton("✕ Fechar")
        self.close_button.clicked.connect(self.close)
        self.close_button.setStyleSheet(
            """
            QPushButton {
                background-color: #757575;
                color: white;
                padding: 12px 24px;
                font-weight: bold;
                font-size: 14px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #616161;
            }
        """
        )
        button_layout.addWidget(self.close_button)

        main_layout.addLayout(button_layout)

        central_widget.setLayout(main_layout)

        # Aplica tema escuro
        self.apply_dark_theme()

    def apply_dark_theme(self):
        """Aplica tema escuro à interface"""
        dark_style = """
            QMainWindow {
                background-color: #2b2b2b;
            }
            QWidget {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QGroupBox {
                border: 1px solid #555555;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 10px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #00aaff;
            }
            QTabWidget::pane {
                border: 1px solid #555555;
                border-radius: 6px;
                background-color: #333333;
            }
            QTabBar::tab {
                background-color: #3c3c3c;
                color: #cccccc;
                padding: 8px 16px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #555555;
                color: #ffffff;
            }
            QTabBar::tab:hover {
                background-color: #4a4a4a;
            }
            QLineEdit, QSpinBox, QComboBox {
                background-color: #3c3c3c;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 5px;
                color: #ffffff;
            }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
                border: 1px solid #00aaff;
            }
            QListWidget {
                background-color: #3c3c3c;
                border: 1px solid #555555;
                border-radius: 4px;
            }
            QListWidget::item {
                padding: 5px;
            }
            QListWidget::item:selected {
                background-color: #00aaff;
            }
            QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid #555555;
                background-color: #3c3c3c;
            }
            QCheckBox::indicator:checked {
                background-color: #00aaff;
                border: 1px solid #00aaff;
            }
            QScrollArea {
                border: none;
            }
            QTextEdit {
                background-color: #1e1e1e;
                border: 1px solid #555555;
                border-radius: 4px;
                color: #ffffff;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background-color: #3c3c3c;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background-color: #00aaff;
                width: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }
            QSlider::sub-page:horizontal {
                background-color: #00aaff;
                border-radius: 3px;
            }
        """
        self.setStyleSheet(dark_style)

    def toggle_bot(self):
        """Ativa/desativa o bot"""
        if not self.executor.active:
            self.start_bot()
        else:
            self.stop_bot()

    def start_bot(self):
        """Inicia o bot"""
        # Carrega regras de healing
        self.executor.healing_rules = self.healing_panel.get_rules()
        self.executor.friend_healing_rules = self.friend_panel.get_friend_rules()

        # Atualiza intervalo
        self.executor.check_interval = self.settings_panel.check_interval.value()

        # Inicia executor
        self.executor.start()
        self.start_time = time.time()

        # Atualiza UI
        self.start_button.setText("⏹ Parar Bot")
        self.start_button.setStyleSheet(
            """
            QPushButton {
                background-color: #f44336;
                color: white;
                padding: 12px 24px;
                font-weight: bold;
                font-size: 14px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
            QPushButton:pressed {
                background-color: #c41000;
            }
        """
        )
        self.status_label.setText("Status: Ativado")
        self.status_indicator.setStyleSheet("color: #44ff44; font-size: 24px;")

        # Inicia timer
        self.timer.start(self.executor.check_interval)

    def stop_bot(self):
        """Para o bot"""
        self.executor.stop()
        self.timer.stop()

        # Atualiza UI
        self.start_button.setText("▶ Iniciar Bot")
        self.start_button.setStyleSheet(
            """
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 12px 24px;
                font-weight: bold;
                font-size: 14px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """
        )
        self.status_label.setText("Status: Desativado")
        self.status_indicator.setStyleSheet("color: #ff4444; font-size: 24px;")

    def reload_config(self):
        """Recarrega as configurações"""
        was_active = self.executor.active
        if was_active:
            self.stop_bot()

        # Recarrega regras
        self.executor.healing_rules = self.healing_panel.get_rules()
        self.executor.friend_healing_rules = self.friend_panel.get_friend_rules()

        self.executor.info("Configurações recarregadas!")

        if was_active:
            self.start_bot()

    def update_bot(self):
        """Atualiza o estado do bot (chamado periodicamente pelo timer)"""
        if not self.executor.active:
            return

        # Executa tick do bot
        self.executor.tick()

        # Verifica healing
        rule = self.executor.check_healing()
        if rule:
            if self.executor.execute_healing(rule):
                self.stats["heals"] += 1

        # Verifica friend healing
        result = self.executor.check_friend_healing()
        if result:
            friend, rule = result
            self.executor.info(f"Curando {friend.name}...")
            self.executor.press_key(rule.hotkey)
            rule.last_used = self.executor.now
            self.stats["heals"] += 1

        # Atualiza UI de status
        self.messages_panel.update_status(self.executor.player)

        # Atualiza CaveBot panel
        self.cavebot_panel.update_position_display()

        # Atualiza estatísticas
        self.messages_panel.heals_label.setText(str(self.stats["heals"]))
        self.messages_panel.macros_label.setText(str(len(self.executor._macros)))

        if self.start_time:
            elapsed = int(time.time() - self.start_time)
            hours = elapsed // 3600
            minutes = (elapsed % 3600) // 60
            seconds = elapsed % 60
            self.messages_panel.time_label.setText(
                f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            )

    def closeEvent(self, event):
        """Evento de fechar janela"""
        if self.executor.active:
            self.stop_bot()

        # Salva storage
        self.executor.storage.save()

        event.accept()


def main():
    """Função principal"""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Define ícone se disponível
    # app.setWindowIcon(QIcon("icon.png"))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
