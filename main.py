# Two sources: TeamSpeak's own badge list - the file the client itself downloads, so a new badge shows up there
# first - and the community forum thread that posts every badge with its redeem code ("Badge Code: X (Available
# until: Y)"), usually the same day. The first run only remembers what's there and says so.
#
# Who hears about it: whoever subscribed themselves (!badges subscribe) plus the admin's 'notify' setting, minus
# whoever unsubscribed (!badges unsubscribe - that works for the admin's picks too: nobody gets messages they don't want).
# Each gets a private message - whoever is offline the moment it's found, when they next connect (the bot starts this
# again for everyone who connects: 'when: join'), or at the latest on the next check. Nobody on the list: the channel.

import html, json, os, re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import ts3bot

LIST = "https://badges-content.teamspeak.com/list"
THREAD = "https://community.teamspeak.com/t/updated-teamspeak-badge-list/25184.rss"
STATE = "/data/state.json"
SUBS = "/data/subscribers.json"   # its own file: state.json not being there yet is what makes the first run the first
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"}
REDEEM = "uplatníš v TeamSpeaku (Nastavení → Účet → Badges) nebo na [url=https://www.myteamspeak.com]myteamspeak.com[/url]"
NO_CODE = {"auto assign", "one-time code", "tba", "unknown", "none", "n/a", "-", ""}
GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
NOTIFY = ts3bot.people("notify")          # UIDs - who they are; what they're called today doesn't matter
SUBSCRIBE = {"odebirat", "odebírat", "odber", "odběr", "prihlasit", "přihlásit", "subscribe", "sub", "on", "ano", "start"}
UNSUBSCRIBE = {"zrusit", "zrušit", "odhlasit", "odhlásit", "unsubscribe", "unsub", "off", "ne", "stop"}


def load_subs():
    """{"in": {uid: name}, "out": [uid]} - who subscribed themselves, and who said no (also to the admin's notify)."""
    try:
        d = json.load(open(SUBS))
        return {"in": dict(d.get("in") or {}), "out": list(d.get("out") or [])}
    except (OSError, ValueError):
        return {"in": {}, "out": []}


def save_subs(subs):
    with open(SUBS, "w") as f:
        json.dump(subs, f)


def recipients(subs):
    return [u for u in dict.fromkeys(NOTIFY + list(subs["in"])) if u not in subs["out"]]


def fetch(url):
    page = ts3bot.fetch(url, headers=UA)
    if not page.ok:
        raise ts3bot.BotError(f"{url} answered HTTP {page.status}")
    return page.content


# The list is protobuf: field 3 = a badge, and in it 1 guid, 2 name, 3 image URL (+ ".svg" / "_details.svg"),
# 4 description, 5 when it was added (seconds, or milliseconds in newer entries).
def varint(b, i):
    r = s = 0
    while True:
        x = b[i]
        i += 1
        r |= (x & 0x7F) << s
        s += 7
        if x < 0x80:
            return r, i


def fields(b):
    i = 0
    while i < len(b):
        key, i = varint(b, i)
        f, t = key >> 3, key & 7
        if t == 0:
            v, i = varint(b, i)
        elif t == 2:
            n, i = varint(b, i)
            v, i = b[i:i + n], i + n
        elif t == 1:
            v, i = b[i:i + 8], i + 8
        elif t == 5:
            v, i = b[i:i + 4], i + 4
        else:
            raise ValueError(f"wire type {t}")
        yield f, t, v


def badges():
    out = {}
    for f, t, v in fields(fetch(LIST)):
        if f != 3 or t != 2:
            continue
        b = {g: (w.decode("utf-8", "replace") if u == 2 else w) for g, u, w in fields(v)}
        if 1 in b and 2 in b:
            added = b.get(5, 0)
            out[b[1]] = {"name": b[2], "description": b.get(4, ""), "image": b.get(3, ""),
                         "added": added / 1000 if added > 10**11 else added}
    if not out:
        raise SystemExit("TeamSpeak's badge list came back empty - its format may have changed")
    return out


def codes():
    """{guid: (code, until)} from the forum thread's newest posts; {} when the forum is down (next time, then)."""
    try:
        root = ET.fromstring(fetch(THREAD))
    except Exception:
        return {}
    out = {}
    for item in root.iter("item"):
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(item.findtext("description") or "")))
        for part in text.split("Name:")[1:]:          # a post may add several badges
            g = GUID.search(part)
            m = re.search(r"Code:\s*(.+?)\s*\(Available until:\s*([^)]*)\)", part)
            if g and m:
                out.setdefault(g.group(0), (m.group(1).strip(), m.group(2).strip()))
    return out


def public(code):
    return code.strip().lower() not in NO_CODE


def tell(text):
    """Into each recipient's outbox (deliver() sends it) - or into the channel when there's nobody on the list."""
    if not WHO:
        ts3bot.tool("say_channel", text=text)
        return
    for uid in WHO:
        box = state.setdefault("outbox", {}).setdefault(uid, [])
        box.append(text)
        del box[:-30]                                  # someone away for months gets the latest 30


def deliver():
    """Private messages to whoever of the recipients is online now - found by UID, not by name; the rest wait."""
    box = {u: t for u, t in (state.get("outbox") or {}).items() if u in WHO and t}
    state["outbox"] = box
    if not box:
        return
    online = set(re.findall(r"^name=.*? uid=(\S+) ", ts3bot.tool("list_online"), re.M))
    for uid, texts in box.items():
        if uid not in online:
            continue
        while texts:
            try:
                ts3bot.tool("message_user", name=uid, text=texts[0])
            except ts3bot.BotError:
                break                                  # gone again: it waits
            texts.pop(0)
            save(state)


def expired(until):
    try:
        return datetime.strptime(until.strip(), "%d.%m.%Y").date() < datetime.now().date()
    except ValueError:
        return False                                   # "unlimited", "TBA", another format: not known to be over


def code_line(code, until):
    if public(code) and expired(until):
        return f"Kód [b]{code}[/b] už vypršel (platil do {until})."
    if public(code):
        return f"Kód: [b]{code}[/b]" + (f" (platí do {until})" if until and until.lower() != "unlimited" else "") + f" · {REDEEM}"
    if code.strip().lower() == "auto assign":
        return "Nemá kód - přidělí se automaticky."
    return "Veřejný kód nemá."


def save(state):
    with open(STATE, "w") as f:
        json.dump(state, f)


state = json.load(open(STATE)) if os.path.exists(STATE) else None
subs = load_subs()
WHO = recipients(subs)

# !badges [subscribe | unsubscribe] (or the Czech odebirat | zrusit): anyone it's published for subscribes or unsubscribes themselves - by their UID.
if ts3bot.trigger == "command":
    word = (ts3bot.args.split() or [""])[0].lower()
    uid, name = ts3bot.user_uid, ts3bot.user_name or "?"
    if not uid:
        raise SystemExit("nevím, kdo to píše")
    if word in SUBSCRIBE:
        subs["in"][uid] = name
        subs["out"] = [u for u in subs["out"] if u != uid]
        save_subs(subs)
        print(f"✅ {name}, odebíráš nové TeamSpeak badges: každou ti napíšu soukromě, i s kódem, jakmile bude známý "
              "(když nebudeš online, dostaneš ji, až přijdeš). Zrušit: [b]!badges unsubscribe[/b]")
    elif word in UNSUBSCRIBE:
        was = uid in WHO
        subs["in"].pop(uid, None)
        if uid not in subs["out"]:
            subs["out"].append(uid)
        save_subs(subs)
        if state is not None and uid in (state.get("outbox") or {}):
            state["outbox"].pop(uid)               # what was still waiting for them goes too
            save(state)
        print("🔕 Hotovo, nové badges ti už psát nebudu. Znovu: [b]!badges subscribe[/b]" if was
              else "Nové badges ti nepíšu ani teď. Odebírat: [b]!badges subscribe[/b]")
    else:
        on = uid in WHO
        print(("🎖 Nové TeamSpeak badges ti píšu soukromě. Zrušit: [b]!badges unsubscribe[/b]" if on
               else "🎖 Nové TeamSpeak badges ti zatím nepíšu. Odebírat: [b]!badges subscribe[/b]")
              + f" · Odebírá {len(WHO)} {'člověk' if len(WHO) == 1 else 'lidi' if 2 <= len(WHO) <= 4 else 'lidí'}.")
    raise SystemExit(0)

# Someone connected: nothing new to look for - only hand over what waits for them (and only if it's one of ours).
if ts3bot.trigger == "join":
    if state is not None and ts3bot.user_uid in WHO:
        deliver()
        save(state)
    raise SystemExit(0)

bl = badges()
cd = codes()

if state is None:   # first run: remember everything, post nothing, say what it watches
    save({"badges": list(bl), "codes": {g: c for g, (c, _) in cd.items()}})
    newest = max(bl.values(), key=lambda b: b["added"])
    when = datetime.fromtimestamp(newest["added"], timezone.utc).strftime("%d.%m.%Y")
    print(f"Hlídám {len(bl)} TeamSpeak badges (a kódy z fóra: {len(cd)}). Nejnovější: {newest['name']} ({when}). "
          + (f"Každou novou napíšu soukromě ({len(WHO)}× - kdo nebude online, dostane ji, až přijde)."
             if WHO else "Každou novou napíšu do kanálu, dokud ji nebude nikdo odebírat.")
          + " Odebírat ji soukromě: [b]!badges subscribe[/b], zrušit: [b]!badges unsubscribe[/b].")
    raise SystemExit(0)

seen = set(state["badges"])
new = sorted((g for g in bl if g not in seen), key=lambda g: bl[g]["added"])
for g in new:
    b = bl[g]
    text = f"🎖 Nová TeamSpeak badge: [b]{b['name']}[/b]" + (f" – {b['description']}" if b["description"] else "")
    text += "\n" + (code_line(*cd[g]) if g in cd else "Kód zatím není známý - napíšu ho, až se objeví.")
    if b["image"]:
        text += f" · [url={b['image']}_details.svg]obrázek[/url]"
    tell(text)
    state["badges"].append(g)
    if g in cd:
        state["codes"][g] = cd[g][0]
    save(state)

# A code that turned up after its badge was announced.
for g, (code, until) in cd.items():
    if g in seen and g not in state["codes"]:
        if public(code) and not expired(until):
            tell(f"🎖 TeamSpeak badge [b]{bl.get(g, {}).get('name', g)}[/b] – {code_line(code, until)}")
        state["codes"][g] = code
        save(state)

deliver()
save(state)
