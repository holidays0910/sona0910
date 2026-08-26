"""
Burgman ESP32 Controller
-------------------------
Kivy app na kumokonekta sa ESP32 gamit ang Classic Bluetooth (SPP).
Features:
  - Listahan ng paired Bluetooth devices + Connect button
  - Quick control buttons: unlock / start / lock
  - Custom terminal: text input + Send + scrollable log

Ito ay gumagamit ng pyjnius para direktang tawagin ang Android Bluetooth API
(BluetoothAdapter, BluetoothSocket) dahil walang built-in Classic Bluetooth
support ang Kivy mismo.

NOTE: Gagana lang ang Bluetooth code na ito kapag naka-build bilang Android APK
(sa pamamagitan ng Buildozer). Hindi ito gagana kapag pinatakbo diretso sa
desktop/PC gamit ang "python main.py" - doon lang gagana ang UI (walang
totoong koneksyon), dahil wala namang Android Bluetooth stack ang PC.
"""

import threading
import traceback
from functools import partial

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.properties import BooleanProperty, ObjectProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.uix.popup import Popup
from kivy.uix.button import Button
from kivy.uix.label import Label

# ---------------------------------------------------------------------------
# Android-specific imports (ligtas na i-try/except para hindi ma-crash sa PC)
# ---------------------------------------------------------------------------
ANDROID = True
try:
    from jnius import autoclass, cast
    from android.permissions import request_permissions, Permission, check_permission
except Exception:
    ANDROID = False

SPP_UUID = "00001101-0000-1000-8000-00805F9B34FB"  # Standard Serial Port Profile UUID


# ---------------------------------------------------------------------------
# Bluetooth Manager - lahat ng Bluetooth logic ay nasa klase na ito
# ---------------------------------------------------------------------------
class BluetoothManager:
    def __init__(self, on_data_received, on_status_change):
        self.on_data_received = on_data_received      # callback(text)
        self.on_status_change = on_status_change       # callback(status_text, connected_bool)
        self.socket = None
        self.input_stream = None
        self.output_stream = None
        self.connected = False
        self._read_thread = None
        self._stop_flag = threading.Event()

        if ANDROID:
            self.BluetoothAdapter = autoclass('android.bluetooth.BluetoothAdapter')
            self.BluetoothDevice = autoclass('android.bluetooth.BluetoothDevice')
            self.BluetoothSocket = autoclass('android.bluetooth.BluetoothSocket')
            self.UUID = autoclass('java.util.UUID')
            self.adapter = self.BluetoothAdapter.getDefaultAdapter()
        else:
            self.adapter = None

    # -- Permissions -------------------------------------------------------
    def request_android_permissions(self, callback=None):
        if not ANDROID:
            if callback:
                callback(True)
            return
        perms = [
            Permission.BLUETOOTH,
            Permission.BLUETOOTH_ADMIN,
        ]
        # Android 12+ (API 31+) na bagong runtime permissions
        try:
            perms += [Permission.BLUETOOTH_CONNECT, Permission.BLUETOOTH_SCAN]
        except AttributeError:
            pass
        perms.append(Permission.ACCESS_FINE_LOCATION)

        def _cb(permissions, grant_results):
            all_ok = all(grant_results) if grant_results else False
            if callback:
                Clock.schedule_once(lambda dt: callback(all_ok))

        request_permissions(perms, _cb)

    # -- Device listing ------------------------------------------------------
    def get_paired_devices(self):
        """Nagbabalik ng listahan ng tuples: (device_name, mac_address)"""
        devices = []
        if not ANDROID or self.adapter is None:
            # Dummy data para sa pag-test sa PC
            return [("ESP32_TEST (walang totoong koneksyon)", "00:00:00:00:00:00")]

        if not self.adapter.isEnabled():
            return []

        bonded = self.adapter.getBondedDevices().toArray()
        for device in bonded:
            name = device.getName()
            address = device.getAddress()
            devices.append((name, address))
        return devices

    def is_bluetooth_enabled(self):
        if not ANDROID or self.adapter is None:
            return False
        return self.adapter.isEnabled()

    # -- Connect / Disconnect ------------------------------------------------
    def connect(self, mac_address):
        """Kumonekta sa ESP32 gamit ang MAC address, sa hiwalay na thread."""
        def _connect_thread():
            try:
                if not ANDROID:
                    # Simulate connection sa PC para lang makita ang UI flow
                    import time
                    time.sleep(1)
                    self.connected = True
                    Clock.schedule_once(lambda dt: self.on_status_change(
                        "Nakakonekta na (TEST MODE - walang totoong ESP32)", True))
                    return

                device = self.adapter.getRemoteDevice(mac_address)
                uuid = self.UUID.fromString(SPP_UUID)

                # I-cancel ang discovery bago kumonekta - pinapabilis at
                # pinapastable ang koneksyon
                if self.adapter.isDiscovering():
                    self.adapter.cancelDiscovery()

                try:
                    self.socket = device.createRfcommSocketToServiceRecord(uuid)
                    self.socket.connect()
                except Exception:
                    # Fallback method gamit ang reflection - kailangan minsan
                    # sa ilang device/ESP32 firmware na hindi standard ang SDP
                    method = device.getClass().getMethod(
                        "createRfcommSocket", [int]
                    )
                    self.socket = method.invoke(device, [1])
                    self.socket.connect()

                self.input_stream = self.socket.getInputStream()
                self.output_stream = self.socket.getOutputStream()
                self.connected = True

                Clock.schedule_once(lambda dt: self.on_status_change(
                    f"Nakakonekta sa {mac_address}", True))

                self._stop_flag.clear()
                self._start_read_loop()

            except Exception as e:
                err = str(e)
                traceback.print_exc()
                Clock.schedule_once(lambda dt: self.on_status_change(
                    f"Bigo ang koneksyon: {err}", False))

        threading.Thread(target=_connect_thread, daemon=True).start()

    def disconnect(self):
        self._stop_flag.set()
        self.connected = False
        try:
            if self.socket is not None:
                self.socket.close()
        except Exception:
            pass
        self.socket = None
        self.input_stream = None
        self.output_stream = None
        if self.on_status_change:
            Clock.schedule_once(lambda dt: self.on_status_change("Naka-disconnect", False))

    # -- Read loop (background thread) ---------------------------------------
    def _start_read_loop(self):
        def _read_thread():
            buffer = b""
            while not self._stop_flag.is_set() and self.connected:
                try:
                    if self.input_stream.available() > 0:
                        byte = self.input_stream.read()
                        if byte == -1:
                            break
                        buffer += bytes([byte])
                        if byte in (10, 13):  # \n o \r - katapusan ng linya
                            if buffer.strip():
                                text = buffer.decode("utf-8", errors="replace").strip()
                                Clock.schedule_once(
                                    partial(lambda dt, t: self.on_data_received(t), t=text)
                                )
                            buffer = b""
                    else:
                        import time
                        time.sleep(0.05)
                except Exception as e:
                    if self.connected:
                        Clock.schedule_once(lambda dt: self.on_status_change(
                            f"Naputol ang koneksyon: {e}", False))
                    self.connected = False
                    break

        self._read_thread = threading.Thread(target=_read_thread, daemon=True)
        self._read_thread.start()

    # -- Send data ------------------------------------------------------------
    def send_command(self, text):
        if not self.connected:
            self.on_data_received("[ERROR] Hindi konektado. I-connect muna ang ESP32.")
            return
        if not ANDROID:
            self.on_data_received(f"[TEST MODE] Ipapadala sana: {text}")
            return
        try:
            data = (text + "\n").encode("utf-8")
            self.output_stream.write(data)
            self.output_stream.flush()
        except Exception as e:
            self.on_data_received(f"[ERROR] Bigo ang pagpapadala: {e}")
            self.connected = False
            Clock.schedule_once(lambda dt: self.on_status_change("Naputol ang koneksyon", False))


# ---------------------------------------------------------------------------
# KV Layout (UI design) - nakasulat dito mismo sa Python string para simple
# ---------------------------------------------------------------------------
KV = '''
ScreenManager:
    ConnectionScreen:
    ControlScreen:

<ConnectionScreen>:
    name: "connect"
    BoxLayout:
        orientation: "vertical"
        padding: 20
        spacing: 15

        Label:
            text: "Burgman ESP32 Controller"
            font_size: "24sp"
            bold: True
            size_hint_y: None
            height: "50dp"

        Label:
            id: bt_status_label
            text: "Suriin kung naka-ON ang Bluetooth ng phone"
            size_hint_y: None
            height: "30dp"
            color: 0.8, 0.6, 0, 1

        Button:
            text: "I-refresh ang listahan ng Paired Devices"
            size_hint_y: None
            height: "55dp"
            on_release: root.refresh_devices()

        ScrollView:
            BoxLayout:
                id: device_list
                orientation: "vertical"
                size_hint_y: None
                height: self.minimum_height
                spacing: 8
                padding: 5

        Label:
            id: conn_status
            text: "Katayuan: Hindi konektado"
            size_hint_y: None
            height: "40dp"
            color: 1, 0.3, 0.3, 1


<ControlScreen>:
    name: "control"
    BoxLayout:
        orientation: "vertical"
        padding: 15
        spacing: 10

        BoxLayout:
            size_hint_y: None
            height: "40dp"
            Label:
                id: control_status
                text: "Hindi konektado"
                color: 1, 0.3, 0.3, 1
            Button:
                text: "Bumalik / Disconnect"
                size_hint_x: 0.5
                on_release: root.go_back()

        GridLayout:
            cols: 3
            size_hint_y: None
            height: "100dp"
            spacing: 10

            Button:
                text: "UNLOCK"
                font_size: "20sp"
                bold: True
                background_color: 0.2, 0.6, 0.9, 1
                on_release: root.send_quick_command("unlock")

            Button:
                text: "START"
                font_size: "20sp"
                bold: True
                background_color: 0.2, 0.8, 0.3, 1
                on_release: root.send_quick_command("start")

            Button:
                text: "LOCK"
                font_size: "20sp"
                bold: True
                background_color: 0.9, 0.3, 0.2, 1
                on_release: root.send_quick_command("lock")

        Label:
            text: "Custom Terminal"
            size_hint_y: None
            height: "30dp"
            bold: True

        BoxLayout:
            size_hint_y: None
            height: "50dp"
            spacing: 8

            TextInput:
                id: custom_input
                hint_text: "i-type ang custom command dito..."
                multiline: False
                on_text_validate: root.send_custom_command()

            Button:
                text: "Send"
                size_hint_x: 0.3
                on_release: root.send_custom_command()

        Label:
            text: "Log / Terminal Output:"
            size_hint_y: None
            height: "25dp"
            bold: True

        ScrollView:
            id: log_scroll
            Label:
                id: log_label
                text: ""
                size_hint_y: None
                height: self.texture_size[1]
                text_size: self.width, None
                halign: "left"
                valign: "top"
                padding: 8, 8

        Button:
            text: "I-clear ang Log"
            size_hint_y: None
            height: "40dp"
            on_release: root.clear_log()
'''


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------
class ConnectionScreen(Screen):
    def on_pre_enter(self):
        app = App.get_running_app()
        if not app.bt.is_bluetooth_enabled() and ANDROID:
            self.ids.bt_status_label.text = "BABALA: Naka-OFF ang Bluetooth. I-ON muna ito."
        else:
            self.ids.bt_status_label.text = "Bluetooth OK. Pumili ng device sa ibaba."
        self.refresh_devices()

    def refresh_devices(self):
        app = App.get_running_app()
        self.ids.device_list.clear_widgets()
        devices = app.bt.get_paired_devices()

        if not devices:
            lbl = Label(text="Walang paired devices. I-pair muna ang ESP32 sa\n"
                             "Bluetooth Settings ng phone bago dito bumalik.",
                        size_hint_y=None, height="60dp")
            self.ids.device_list.add_widget(lbl)
            return

        for name, address in devices:
            btn = Button(
                text=f"{name}\n[{address}]",
                size_hint_y=None,
                height="65dp",
            )
            btn.bind(on_release=partial(self.connect_to_device, address, name))
            self.ids.device_list.add_widget(btn)

    def connect_to_device(self, address, name, *args):
        app = App.get_running_app()
        self.ids.conn_status.text = f"Kumokonekta sa {name}..."
        app.bt.connect(address)

    def on_status_change(self, status_text, connected):
        self.ids.conn_status.text = f"Katayuan: {status_text}"
        if connected:
            app = App.get_running_app()
            control_screen = app.sm.get_screen("control")
            control_screen.ids.control_status.text = status_text
            control_screen.ids.control_status.color = (0.2, 0.9, 0.2, 1)
            app.sm.current = "control"


class ControlScreen(Screen):
    def go_back(self):
        app = App.get_running_app()
        app.bt.disconnect()
        app.sm.current = "connect"

    def send_quick_command(self, command):
        app = App.get_running_app()
        app.bt.send_command(command)
        self.append_log(f">> {command}")

    def send_custom_command(self):
        app = App.get_running_app()
        text = self.ids.custom_input.text.strip()
        if text:
            app.bt.send_command(text)
            self.append_log(f">> {text}")
            self.ids.custom_input.text = ""

    def append_log(self, text):
        log_label = self.ids.log_label
        if log_label.text:
            log_label.text += f"\n{text}"
        else:
            log_label.text = text
        # I-scroll pababa papunta sa pinakahuling linya
        Clock.schedule_once(lambda dt: setattr(self.ids.log_scroll, "scroll_y", 0), 0.05)

    def clear_log(self):
        self.ids.log_label.text = ""

    def on_data_received(self, text):
        self.append_log(f"<< {text}")

    def on_status_change(self, status_text, connected):
        self.ids.control_status.text = status_text
        self.ids.control_status.color = (0.2, 0.9, 0.2, 1) if connected else (1, 0.3, 0.3, 1)
        if not connected:
            self.append_log(f"[STATUS] {status_text}")


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------
class BurgmanApp(App):
    def build(self):
        self.sm = Builder.load_string(KV)

        # I-link ang callbacks pagkatapos magawa ang screens
        connect_screen = self.sm.get_screen("connect")
        control_screen = self.sm.get_screen("control")

        self.bt = BluetoothManager(
            on_data_received=control_screen.on_data_received,
            on_status_change=self._route_status_change,
        )

        self._connect_screen = connect_screen
        self._control_screen = control_screen

        if ANDROID:
            self.bt.request_android_permissions(self._on_permissions_result)

        return self.sm

    def _on_permissions_result(self, all_granted):
        if not all_granted:
            popup = Popup(
                title="Kailangan ng Permissions",
                content=Label(
                    text="Kailangan ng Bluetooth at Location permissions\n"
                         "para gumana ang app. Paki-allow sa Settings."
                ),
                size_hint=(0.8, 0.4),
            )
            popup.open()

    def _route_status_change(self, status_text, connected):
        # I-update pareho ang connection screen at control screen
        self._connect_screen.on_status_change(status_text, connected)
        self._control_screen.on_status_change(status_text, connected)

    def on_stop(self):
        # Linisin ang koneksyon kapag isinara ang app
        if hasattr(self, "bt"):
            self.bt.disconnect()


if __name__ == "__main__":
    BurgmanApp().run()
