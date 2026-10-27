import asyncio
import json
import os
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from telethon import TelegramClient
from telethon.errors import FloodWaitError, SessionPasswordNeededError

FIELD_H = 96


def make_field(hint, password=False):
    return TextInput(hint_text=hint, multiline=False, password=password,
                     size_hint_y=None, height=FIELD_H, write_tab=False)


def toggle(widget, visible):
    widget.opacity = 1 if visible else 0
    widget.disabled = not visible
    widget.height = FIELD_H if visible else 0


class CleanerApp(App):
    title = "TG Cleaner"

    def build(self):
        self.client = None
        self.step = "login"
        self.busy = False
        self.phone_num = ""
        self.hist_path = os.path.join(self.user_data_dir, "history.json")
        self.history = self._load_history()

        root = BoxLayout(orientation="vertical", padding=12, spacing=8)
        self.status = Label(text="Enter your Telegram API details",
                            size_hint_y=None, height=70)
        self.status.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))
        self.api_id = make_field("API ID")
        self.api_id.input_filter = "int"
        self.api_hash = make_field("API Hash")
        self.phone = make_field("Phone number (+855...)")
        self.code = make_field("Login code from Telegram")
        self.pw = make_field("2FA password", password=True)
        self.btn = Button(text="Connect", size_hint_y=None, height=110)
        self.btn.bind(on_release=lambda *_: self._run(self.on_button()))

        self.log = Label(text="", size_hint_y=None, halign="left", valign="top")
        self.log.bind(width=lambda i, w: setattr(i, "text_size", (w, None)),
                      texture_size=lambda i, s: setattr(i, "height", s[1]))
        self.scroll = ScrollView()
        self.scroll.add_widget(self.log)

        for w in (self.status, self.api_id, self.api_hash, self.phone,
                  self.code, self.pw, self.btn, self.scroll):
            root.add_widget(w)
        self._refresh_ui()
        self._render_log()
        return root

    # ---------- helpers ----------
    def _run(self, coro):
        asyncio.ensure_future(coro)

    def _refresh_ui(self):
        s = self.step
        toggle(self.api_id, s == "login")
        toggle(self.api_hash, s == "login")
        toggle(self.phone, s == "login")
        toggle(self.code, s == "code")
        toggle(self.pw, s == "password")
        self.btn.text = {"login": "Connect", "code": "Sign in",
                         "password": "Sign in", "ready": "Clean account"}[s]

    def set_status(self, text):
        self.status.text = text

    def _load_history(self):
        try:
            with open(self.hist_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _save_history(self):
        try:
            with open(self.hist_path, "w", encoding="utf-8") as f:
                json.dump(self.history[-5000:], f, ensure_ascii=False)
        except Exception:
            pass

    def add_log(self, msg):
        self.history.append({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "m": msg})
        self._save_history()
        self._render_log()

    def _render_log(self):
        lines = [f"{h['t']}  {h['m']}" for h in self.history[-300:]]
        self.log.text = "\n".join(lines) if lines else "History is empty."
        Clock.schedule_once(lambda *_: setattr(self.scroll, "scroll_y", 0), 0.1)

    # ---------- login flow ----------
    async def on_button(self):
        if self.busy:
            return
        self.busy = True
        try:
            if self.step == "login":
                await self.do_login()
            elif self.step == "code":
                await self.do_code()
            elif self.step == "password":
                await self.do_password()
            elif self.step == "ready":
                self.confirm()
        except Exception as e:
            self.set_status(f"Error: {e}")
        finally:
            self.busy = False

    async def do_login(self):
        api_id = int(self.api_id.text.strip())
        api_hash = self.api_hash.text.strip()
        phone = self.phone.text.strip()
        self.client = TelegramClient(
            os.path.join(self.user_data_dir, "session"), api_id, api_hash)
        self.set_status("Connecting...")
        await self.client.connect()
        if await self.client.is_user_authorized():
            self.step = "ready"
            self.set_status("Already logged in. Ready.")
        else:
            await self.client.send_code_request(phone)
            self.phone_num = phone
            self.step = "code"
            self.set_status("Code sent. Enter it below.")
        self._refresh_ui()

    async def do_code(self):
        try:
            await self.client.sign_in(self.phone_num, self.code.text.strip())
        except SessionPasswordNeededError:
            self.step = "password"
            self.set_status("2FA password required.")
            self._refresh_ui()
            return
        self.step = "ready"
        self.set_status("Logged in. Ready.")
        self._refresh_ui()

    async def do_password(self):
        await self.client.sign_in(password=self.pw.text)
        self.step = "ready"
        self.set_status("Logged in. Ready.")
        self._refresh_ui()

    # ---------- cleaning ----------
    def confirm(self):
        box = BoxLayout(orientation="vertical", spacing=8, padding=8)
        msg = Label(text="This will LEAVE all groups/channels and DELETE all "
                         "chats. It cannot be undone.\nType DELETE to continue.")
        msg.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))
        ti = make_field("DELETE")
        row = BoxLayout(size_hint_y=None, height=110, spacing=8)
        cancel = Button(text="Cancel")
        go = Button(text="Start")
        row.add_widget(cancel)
        row.add_widget(go)
        for w in (msg, ti, row):
            box.add_widget(w)
        pop = Popup(title="Confirm", content=box, size_hint=(0.92, 0.6))

        def start(*_):
            if ti.text.strip() == "DELETE":
                pop.dismiss()
                self._run(self.clean())

        go.bind(on_release=start)
        cancel.bind(on_release=lambda *_: pop.dismiss())
        pop.open()

    async def clean(self):
        if self.busy:
            return
        self.busy = True
        self.btn.disabled = True
        done = failed = 0
        try:
            self.add_log("--- Cleaning started ---")
            self.set_status("Loading chat list...")
            me = await self.client.get_me()
            dialogs = [d async for d in self.client.iter_dialogs()
                       if d.entity.id != me.id]
            total = len(dialogs)
            self.add_log(f"Found {total} chats")

            for i, d in enumerate(dialogs, 1):
                if d.is_group:
                    kind, action = "Group", "Left"
                elif d.is_channel:
                    kind, action = "Channel", "Left"
                elif getattr(d.entity, "bot", False):
                    kind, action = "Bot", "Deleted"
                else:
                    kind, action = "Chat", "Deleted"
                name = d.name or str(d.entity.id)
                self.set_status(f"{i}/{total}: {name}")

                for _ in range(5):
                    try:
                        await self.client.delete_dialog(d.entity, revoke=True)
                        done += 1
                        self.add_log(f"[OK] {action} {kind}: {name}")
                        break
                    except FloodWaitError as e:
                        self.add_log(f"[WAIT] Telegram limit, waiting {e.seconds}s")
                        await asyncio.sleep(e.seconds + 1)
                    except Exception as e:
                        failed += 1
                        self.add_log(f"[FAIL] {kind}: {name} ({e})")
                        break
                await asyncio.sleep(1.0)

            self.add_log(f"--- Finished: {done} ok, {failed} failed ---")
            self.set_status(f"Finished. {done} ok, {failed} failed.")
        except Exception as e:
            self.add_log(f"[ERROR] {e}")
            self.set_status(f"Error: {e}")
        finally:
            self.btn.disabled = False
            self.busy = False


if __name__ == "__main__":
    app = CleanerApp()
    asyncio.run(app.async_run(async_lib="asyncio"))
