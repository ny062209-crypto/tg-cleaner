import asyncio
import json
import os
import shutil
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ListProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox  # noqa: F401 (used from kv)
from kivy.uix.floatlayout import FloatLayout  # noqa: F401
from kivy.uix.image import Image  # noqa: F401
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.screenmanager import NoTransition, Screen, ScreenManager
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.widget import Widget
from kivy.utils import escape_markup
from telethon import TelegramClient
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telethon.tl.functions.channels import DeleteChannelRequest
from telethon.tl.types import Channel, ChatPhotoEmpty, UserProfilePhotoEmpty

VERSION = "1.1.1"
HERE = os.path.dirname(os.path.abspath(__file__))
KHMER_FONT = os.path.join(HERE, "fonts", "khmer.ttf")
if not os.path.exists(KHMER_FONT):
    KHMER_FONT = None

PALETTE = [
    [0.90, 0.35, 0.35, 1], [0.95, 0.60, 0.20, 1], [0.60, 0.45, 0.85, 1],
    [0.30, 0.70, 0.45, 1], [0.25, 0.65, 0.85, 1], [0.85, 0.40, 0.65, 1],
]

KV = """
<ChatRow>:
    orientation: 'horizontal'
    size_hint_y: None
    height: dp(64)
    spacing: dp(6)
    padding: dp(4)
    canvas.after:
        Color:
            rgba: 1, 1, 1, .08
        Line:
            points: self.x, self.y, self.right, self.y
    CheckBox:
        size_hint_x: None
        width: dp(46)
        active: root.selected
        on_active: root.on_toggle(self.active)
    FloatLayout:
        size_hint_x: None
        width: dp(54)
        Label:
            markup: True
            text: root.letter
            bold: True
            size_hint: None, None
            size: dp(46), dp(46)
            pos_hint: {'center_x': .5, 'center_y': .5}
            canvas.before:
                Color:
                    rgba: root.color
                Ellipse:
                    pos: self.pos
                    size: self.size
        Image:
            source: root.avatar
            fit_mode: 'cover'
            size_hint: None, None
            size: dp(46), dp(46)
            pos_hint: {'center_x': .5, 'center_y': .5}
            opacity: 1 if root.avatar else 0
    BoxLayout:
        orientation: 'vertical'
        Label:
            markup: True
            text: root.title
            halign: 'left'
            valign: 'middle'
            text_size: self.size
            shorten: True
            shorten_from: 'right'
            font_size: sp(16)
        Label:
            markup: True
            text: root.subtitle
            halign: 'left'
            valign: 'middle'
            text_size: self.size
            shorten: True
            font_size: sp(12)
            color: .65, .65, .65, 1
"""


def is_khmer(ch):
    return "\u1780" <= ch <= "\u17ff" or "\u19e0" <= ch <= "\u19ff"


def mixed(text):
    """Escape markup; wrap Khmer runs in the bundled Khmer font if present."""
    text = escape_markup(text)
    if not KHMER_FONT:
        return text
    out, cur = [], False
    for ch in text:
        if is_khmer(ch):
            want = True
        elif ch.isspace() or ch == "\u200b":
            want = cur
        else:
            want = False
        if want != cur:
            out.append(f"[font={KHMER_FONT}]" if want else "[/font]")
            cur = want
        out.append(ch)
    if cur:
        out.append("[/font]")
    return "".join(out)


def make_field(hint, password=False):
    return TextInput(hint_text=hint, multiline=False, password=password,
                     size_hint_y=None, height=dp(48), write_tab=False)


def toggle(widget, visible):
    widget.opacity = 1 if visible else 0
    widget.disabled = not visible
    widget.height = dp(48) if visible else 0


class ChatRow(RecycleDataViewBehavior, BoxLayout):
    index = None
    rv = None
    title = StringProperty("")
    subtitle = StringProperty("")
    letter = StringProperty("")
    avatar = StringProperty("")
    selected = BooleanProperty(False)
    color = ListProperty([0.3, 0.5, 0.8, 1])

    def refresh_view_attrs(self, rv, index, data):
        self.index = index
        self.rv = rv
        return super().refresh_view_attrs(rv, index, data)

    def on_toggle(self, active):
        if self.rv is None or self.index is None:
            return
        d = self.rv.data[self.index]
        if d.get("selected") == active:
            return
        d["selected"] = active
        App.get_running_app().on_select(d["cid"], active)


class CleanerApp(App):
    title = "TG Cleaner"

    # ------------------------------------------------------------ build
    def build(self):
        Builder.load_string(KV)
        self.client = None
        self.step = "login"
        self.busy = False
        self.phone_num = ""
        self.items = []
        self.entities = {}
        self.selected = set()
        self.filter = "all"
        self.avatar_task = None
        self.avatar_dir = os.path.join(self.user_data_dir, "avatars")
        os.makedirs(self.avatar_dir, exist_ok=True)
        self.hist_path = os.path.join(self.user_data_dir, "history.json")
        self.cfg_path = os.path.join(self.user_data_dir, "config.json")
        self.history = self._load_json(self.hist_path, [])
        self.cfg = self._load_json(self.cfg_path, {})

        root = BoxLayout(orientation="vertical", padding=8, spacing=6)
        self.status = Label(text=f"TG Cleaner v{VERSION}", size_hint_y=None,
                            height=dp(44), halign="center")
        self.status.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))
        self.sm = ScreenManager(transition=NoTransition())
        self.sm.add_widget(self._login_screen())
        self.sm.add_widget(self._chats_screen())
        self.sm.add_widget(self._history_screen())
        root.add_widget(self.status)
        root.add_widget(self.sm)
        self._refresh_login()
        self._render_log()
        return root

    def on_start(self):
        if self.cfg.get("api_id") and self.cfg.get("api_hash"):
            asyncio.ensure_future(self.auto_login())

    # ------------------------------------------------------------ screens
    def _login_screen(self):
        s = Screen(name="login")
        box = BoxLayout(orientation="vertical", spacing=8, padding=4)
        self.api_id = make_field("API ID")
        self.api_id.input_filter = "int"
        self.api_id.text = str(self.cfg.get("api_id", ""))
        self.api_hash = make_field("API Hash")
        self.api_hash.text = self.cfg.get("api_hash", "")
        self.phone = make_field("Phone number (+855...)")
        self.phone.text = self.cfg.get("phone", "")
        self.code = make_field("Login code from Telegram")
        self.pw = make_field("2FA password", password=True)
        self.login_btn = Button(text="Connect", size_hint_y=None, height=dp(56))
        self.login_btn.bind(on_release=lambda *_: asyncio.ensure_future(self.on_login_btn()))
        hist = Button(text="History", size_hint_y=None, height=dp(44))
        hist.bind(on_release=lambda *_: self.show_history("login"))
        for w in (self.api_id, self.api_hash, self.phone, self.code, self.pw,
                  self.login_btn, hist, Widget()):
            box.add_widget(w)
        s.add_widget(box)
        return s

    def _chats_screen(self):
        s = Screen(name="chats")
        box = BoxLayout(orientation="vertical", spacing=6)

        top = BoxLayout(size_hint_y=None, height=dp(44), spacing=6)
        for text, cb in (("Reload", lambda *_: asyncio.ensure_future(self.load_chats())),
                         ("Select all", lambda *_: self.toggle_all()),
                         ("Logout", lambda *_: asyncio.ensure_future(self.do_logout()))):
            b = Button(text=text)
            b.bind(on_release=cb)
            top.add_widget(b)

        flt = BoxLayout(size_hint_y=None, height=dp(40), spacing=4)
        for text, key in (("All", "all"), ("Chats", "chats"),
                          ("Groups", "groups"), ("Channels", "channels")):
            b = ToggleButton(text=text, group="flt", allow_no_selection=False,
                             state="down" if key == "all" else "normal")
            b.bind(on_release=lambda _w, k=key: self.set_filter(k))
            flt.add_widget(b)

        self.rv = RecycleView(viewclass="ChatRow")
        lay = RecycleBoxLayout(default_size=(None, dp(64)),
                               default_size_hint=(1, None), size_hint_y=None,
                               orientation="vertical")
        lay.bind(minimum_height=lay.setter("height"))
        self.rv.add_widget(lay)

        self.owned_btn = ToggleButton(
            text="Also delete chats I OWN (removes for everyone)",
            size_hint_y=None, height=dp(40))
        self.del_btn = Button(text="Delete selected (0)", size_hint_y=None,
                              height=dp(56), disabled=True)
        self.del_btn.bind(on_release=lambda *_: self.ask_delete())
        hist = Button(text="History", size_hint_y=None, height=dp(40))
        hist.bind(on_release=lambda *_: self.show_history("chats"))

        for w in (top, flt, self.rv, self.owned_btn, self.del_btn, hist):
            box.add_widget(w)
        s.add_widget(box)
        return s

    def _history_screen(self):
        s = Screen(name="history")
        box = BoxLayout(orientation="vertical", spacing=6)
        self.log = Label(text="", size_hint_y=None, halign="left", valign="top")
        self.log.bind(width=lambda i, w: setattr(i, "text_size", (w, None)),
                      texture_size=lambda i, s_: setattr(i, "height", s_[1]))
        self.scroll = ScrollView()
        self.scroll.add_widget(self.log)
        back = Button(text="Back", size_hint_y=None, height=dp(48))
        back.bind(on_release=lambda *_: self.go_back())
        box.add_widget(self.scroll)
        box.add_widget(back)
        s.add_widget(box)
        return s

    def show_history(self, came_from):
        self._back_to = came_from
        self.sm.current = "history"
        self._render_log()

    def go_back(self):
        self.sm.current = getattr(self, "_back_to", "login")

    # ------------------------------------------------------------ storage / log
    @staticmethod
    def _load_json(path, default):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def _save_json(self, path, data):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass

    def set_status(self, text):
        self.status.text = text

    def add_log(self, msg):
        self.history.append({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "m": msg})
        self._save_json(self.hist_path, self.history[-5000:])
        self._render_log()

    def _render_log(self):
        lines = [f"{h['t']}  {h['m']}" for h in self.history[-300:]]
        self.log.text = "\n".join(lines) if lines else "History is empty."
        Clock.schedule_once(lambda *_: setattr(self.scroll, "scroll_y", 0), 0.1)

    # ------------------------------------------------------------ login flow
    def _refresh_login(self):
        s = self.step
        toggle(self.api_id, s == "login")
        toggle(self.api_hash, s == "login")
        toggle(self.phone, s == "login")
        toggle(self.code, s == "code")
        toggle(self.pw, s == "password")
        self.login_btn.text = "Connect" if s == "login" else "Sign in"

    def _new_client(self, api_id, api_hash):
        return TelegramClient(os.path.join(self.user_data_dir, "session"),
                              api_id, api_hash)

    async def auto_login(self):
        try:
            self.client = self._new_client(int(self.cfg["api_id"]), self.cfg["api_hash"])
            await self.client.connect()
            if await self.client.is_user_authorized():
                await self.enter_chats()
        except Exception:
            pass

    async def on_login_btn(self):
        if self.busy:
            return
        self.busy = True
        ok = False
        try:
            if self.step == "login":
                ok = await self.do_login()
            elif self.step == "code":
                ok = await self.do_code()
            elif self.step == "password":
                ok = await self.do_password()
        except Exception as e:
            self.set_status(f"Error: {e}")
        finally:
            self.busy = False
        if ok:
            await self.enter_chats()

    async def do_login(self):
        api_id = int(self.api_id.text.strip())
        api_hash = self.api_hash.text.strip()
        phone = self.phone.text.strip()
        self.cfg = {"api_id": api_id, "api_hash": api_hash, "phone": phone}
        self._save_json(self.cfg_path, self.cfg)
        self.client = self._new_client(api_id, api_hash)
        self.set_status("Connecting...")
        await self.client.connect()
        if await self.client.is_user_authorized():
            return True
        await self.client.send_code_request(phone)
        self.phone_num = phone
        self.step = "code"
        self.set_status("Code sent. Enter it below.")
        self._refresh_login()
        return False

    async def do_code(self):
        try:
            await self.client.sign_in(self.phone_num, self.code.text.strip())
        except SessionPasswordNeededError:
            self.step = "password"
            self.set_status("2FA password required.")
            self._refresh_login()
            return False
        return True

    async def do_password(self):
        await self.client.sign_in(password=self.pw.text)
        return True

    async def do_logout(self):
        if self.busy:
            return
        if self.avatar_task:
            self.avatar_task.cancel()
        try:
            await self.client.log_out()
        except Exception:
            pass
        self.client = None
        self.step = "login"
        self.items, self.entities = [], {}
        self.selected.clear()
        self.rv.data = []
        shutil.rmtree(self.avatar_dir, ignore_errors=True)
        os.makedirs(self.avatar_dir, exist_ok=True)
        self.code.text = ""
        self.pw.text = ""
        self._refresh_login()
        self.set_status("Logged out.")
        self.sm.current = "login"

    # ------------------------------------------------------------ chat list
    async def enter_chats(self):
        self.sm.current = "chats"
        await self.load_chats()

    @staticmethod
    def kind_of(d):
        if d.is_group:
            return "Group"
        if d.is_channel:
            return "Channel"
        if getattr(d.entity, "bot", False):
            return "Bot"
        return "Chat"

    @staticmethod
    def _fname(cid):
        return str(cid).replace("-", "m") + ".jpg"

    async def load_chats(self):
        if self.busy:
            return
        self.busy = True
        try:
            if self.avatar_task:
                self.avatar_task.cancel()
            self.set_status("Loading chats...")
            me = await self.client.get_me()
            items, ents = [], {}
            async for d in self.client.iter_dialogs():
                ent = d.entity
                if ent.id == me.id:
                    continue
                kind = self.kind_of(d)
                owner = bool(getattr(ent, "creator", False))
                name = d.name or "(no name)"
                sub = kind
                if owner:
                    sub += " · you own it"
                uname = getattr(ent, "username", None)
                if uname:
                    sub += f" · @{uname}"
                path = os.path.join(self.avatar_dir, self._fname(d.id))
                ents[d.id] = ent
                items.append({
                    "cid": d.id, "name": name, "kind": kind, "owner": owner,
                    "title": mixed(name), "subtitle": escape_markup(sub),
                    "letter": mixed(name.strip()[:1].upper() or "?"),
                    "color": PALETTE[abs(d.id) % len(PALETTE)],
                    "avatar": path if os.path.exists(path) else "",
                })
            self.items, self.entities = items, ents
            self.selected &= {it["cid"] for it in items}
            self.apply_filter()
            self.set_status(f"{len(items)} chats loaded. Tick the ones to delete.")
        except Exception as e:
            self.set_status(f"Error: {e}")
        finally:
            self.busy = False
            self.update_count()
        self.avatar_task = asyncio.ensure_future(self.load_avatars())

    async def load_avatars(self):
        n = 0
        for it in list(self.items):
            if it["avatar"]:
                continue
            ent = self.entities.get(it["cid"])
            photo = getattr(ent, "photo", None)
            if ent is None or photo is None or isinstance(
                    photo, (ChatPhotoEmpty, UserProfilePhotoEmpty)):
                continue
            path = os.path.join(self.avatar_dir, self._fname(it["cid"]))
            try:
                res = await self.client.download_profile_photo(
                    ent, file=path, download_big=False)
            except FloodWaitError:
                await asyncio.sleep(5)
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                continue
            if res:
                it["avatar"] = res
                n += 1
                if n % 10 == 0:
                    self.apply_filter()
            await asyncio.sleep(0.05)
        self.apply_filter()

    def set_filter(self, key):
        self.filter = key
        self.apply_filter()

    def apply_filter(self):
        f = self.filter
        out = []
        for it in self.items:
            k = it["kind"]
            if f == "chats" and k not in ("Chat", "Bot"):
                continue
            if f == "groups" and k != "Group":
                continue
            if f == "channels" and k != "Channel":
                continue
            out.append({
                "cid": it["cid"], "title": it["title"], "subtitle": it["subtitle"],
                "letter": it["letter"], "avatar": it["avatar"], "color": it["color"],
                "selected": it["cid"] in self.selected,
            })
        self.rv.data = out
        self.update_count()

    def on_select(self, cid, active):
        if active:
            self.selected.add(cid)
        else:
            self.selected.discard(cid)
        self.update_count()

    def toggle_all(self):
        vis = [d["cid"] for d in self.rv.data]
        if vis and all(c in self.selected for c in vis):
            self.selected.difference_update(vis)
        else:
            self.selected.update(vis)
        self.apply_filter()

    def update_count(self):
        n = len(self.selected)
        self.del_btn.text = f"Delete selected ({n})"
        self.del_btn.disabled = n == 0 or self.busy

    # ------------------------------------------------------------ deleting
    def ask_delete(self):
        if self.busy:
            return
        chosen = [it for it in self.items if it["cid"] in self.selected]
        if not chosen:
            return
        del_owned = self.owned_btn.state == "down"
        owned = [it for it in chosen if it["owner"]]
        need_type = len(chosen) >= 10 or (del_owned and bool(owned))

        text = (f"Delete {len(chosen)} selected chat(s)?\n"
                "Groups/channels: you leave.\n"
                "Private chats: history deleted for both sides.\n"
                "This cannot be undone.")
        if del_owned and owned:
            text += f"\n{len(owned)} chat(s) you OWN will be DELETED FOR EVERYONE."
        elif owned:
            text += (f"\n{len(owned)} chat(s) are owned by you and may fail to "
                     "leave. Turn on the 'OWN' switch to delete them.")
        if need_type:
            text += "\nType DELETE to continue."

        box = BoxLayout(orientation="vertical", spacing=8, padding=8)
        msg = Label(text=text, halign="center")
        msg.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))
        box.add_widget(msg)
        ti = None
        if need_type:
            ti = make_field("DELETE")
            box.add_widget(ti)
        row = BoxLayout(size_hint_y=None, height=dp(56), spacing=8)
        cancel = Button(text="Cancel")
        go = Button(text="Delete")
        row.add_widget(cancel)
        row.add_widget(go)
        box.add_widget(row)
        pop = Popup(title="Confirm", content=box, size_hint=(0.94, 0.7))

        def start(*_):
            if ti is not None and ti.text.strip() != "DELETE":
                return
            pop.dismiss()
            asyncio.ensure_future(self.delete_selected(chosen, del_owned))

        go.bind(on_release=start)
        cancel.bind(on_release=lambda *_: pop.dismiss())
        pop.open()

    async def _delete_one(self, ent, kind, owner, del_owned):
        if owner and del_owned and isinstance(ent, Channel):
            await self.client(DeleteChannelRequest(ent))
            return "Deleted for everyone"
        await self.client.delete_dialog(ent, revoke=True)
        return "Left" if kind in ("Group", "Channel") else "Deleted"

    async def delete_selected(self, chosen, del_owned):
        if self.busy:
            return
        self.busy = True
        if self.avatar_task:
            self.avatar_task.cancel()
        self.update_count()
        ok = failed = 0
        removed = set()
        total = len(chosen)
        self.add_log(f"--- Deleting {total} selected ---")
        try:
            for i, it in enumerate(chosen, 1):
                ent = self.entities.get(it["cid"])
                name, kind, owner = it["name"], it["kind"], it["owner"]
                self.set_status(f"{i}/{total}: {name}")
                for _ in range(5):
                    try:
                        action = await self._delete_one(ent, kind, owner, del_owned)
                        ok += 1
                        removed.add(it["cid"])
                        self.add_log(f"[OK] {action} {kind}: {name}")
                        break
                    except FloodWaitError as e:
                        self.add_log(f"[WAIT] Telegram limit, waiting {e.seconds}s")
                        await asyncio.sleep(e.seconds + 1)
                    except Exception as e:
                        failed += 1
                        msg = str(e)
                        hint = ""
                        if owner and "creator" in msg.lower():
                            hint = " -> you own it: turn on the OWN switch to delete it"
                        self.add_log(f"[FAIL] {kind}: {name} ({msg}){hint}")
                        break
                if i % 10 == 0:
                    self.items = [x for x in self.items if x["cid"] not in removed]
                    self.apply_filter()
                await asyncio.sleep(1.0)

            if removed:
                self.set_status("Verifying with Telegram...")
                await asyncio.sleep(2.0)
                names = {it["cid"]: it["name"] for it in chosen}
                still = set()
                try:
                    async for d in self.client.iter_dialogs():
                        if d.id in removed:
                            still.add(d.id)
                except Exception as e:
                    self.add_log(f"[WARN] Could not verify: {e}")
                if still:
                    for cid in still:
                        self.add_log(
                            f"[STILL THERE] {names.get(cid, cid)} - Telegram "
                            "did not remove it (may need a few minutes to "
                            "sync, or it is a bot shortcut Telegram keeps)")
                    ok -= len(still)
                    failed += len(still)
                else:
                    self.add_log("[VERIFIED] All deleted chats confirmed gone from Telegram")

            self.add_log(f"--- Finished: {ok} ok, {failed} failed ---")
            self.set_status(f"Finished. {ok} ok, {failed} failed.")
        except Exception as e:
            self.add_log(f"[ERROR] {e}")
            self.set_status(f"Error: {e}")
        finally:
            self.items = [x for x in self.items if x["cid"] not in removed]
            self.selected -= removed
            self.busy = False
            self.apply_filter()


if __name__ == "__main__":
    app = CleanerApp()
    asyncio.run(app.async_run(async_lib="asyncio"))
