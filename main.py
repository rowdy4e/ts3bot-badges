# Two sources: TeamSpeak's own badge list - the file the client itself downloads, so a new badge shows up there
# first - and the community forum thread that posts every badge with its redeem code ("Badge Code: X (Available
# until: Y)"), usually the same day. The first check only remembers what's there and says so.
#
# Who hears about it: whoever subscribed themselves (!badges subscribe) plus the admin's 'notify' setting, minus
# whoever unsubscribed (!badges unsubscribe - that works for the admin's picks too: nobody gets messages they don't want).
# Each gets a private message - whoever is offline the moment it's found, when they next connect ('join'), or at the
# latest on the next check. Nobody on the list: the channel.
#
# It runs all the time ('when: always'): its checks, the !badges commands and people connecting come to it as events
# (ts3bot.serve), so a command is answered at once - no container started for it. Its memory lives in /data, read
# at each event: a restart (or a crash) loses nothing.

import html, json, os, re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import ts3bot

LIST = "https://badges-content.teamspeak.com/list"
THREAD = "https://community.teamspeak.com/t/updated-teamspeak-badge-list/25184.rss"
STATE = "/data/state.json"
SUBS = "/data/subscribers.json"   # its own file: state.json not being there yet is what makes the first run the first
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"}
REDEEM = "redeem it in TeamSpeak (Settings → Account → Badges) or at [url=https://www.myteamspeak.com]myteamspeak.com[/url]"
NO_CODE = {"auto assign", "one-time code", "tba", "unknown", "none", "n/a", "-", ""}
GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
NOTIFY = ts3bot.people("notify")          # UIDs - who they are; what they're called today doesn't matter
SUBSCRIBE = {"odebirat", "odebírat", "odber", "odběr", "prihlasit", "přihlásit", "subscribe", "sub", "on", "ano", "start"}
UNSUBSCRIBE = {"zrusit", "zrušit", "odhlasit", "odhlásit", "unsubscribe", "unsub", "off", "ne", "stop"}
LATEST = {"latest", "last", "newest", "new", "posledni", "poslední", "nejnovejsi", "nejnovější"}
FORGET = {"forget", "again", "test", "zapomen", "zapomeň"}
HELP = {"", "help", "--help", "-h", "-?", "?", "napoveda", "nápověda"}
BURST = 3                                 # more new badges than this at once: the newest in full, the rest by name


def write(path, data):
    """Whole or not at all: a run that's stopped mid-write (a crash, its time limit) leaves the old file, never half of one."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_subs():
    """{"in": {uid: name}, "out": [uid]} - who subscribed themselves, and who said no (also to the admin's notify)."""
    if not os.path.exists(SUBS):
        return {"in": {}, "out": []}
    try:
        d = json.load(open(SUBS))
        return {"in": dict(d.get("in") or {}), "out": list(d.get("out") or [])}
    except (OSError, ValueError) as e:
        # Never "nobody subscribed" over a file that's there: the next subscribe would overwrite everyone.
        raise RuntimeError(f"{SUBS} can't be read ({e}) - left as it is; nobody is told anything until it's fixed")


def save_subs(subs):
    write(SUBS, subs)


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
        raise RuntimeError("TeamSpeak's badge list came back empty - its format may have changed")
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
        queue(uid, text)


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
        return f"Code [b]{code}[/b] has expired (it was valid until {until})."
    if public(code):
        return f"Code: [b]{code}[/b]" + (f" (valid until {until})" if until and until.lower() != "unlimited" else "") + f" · {REDEEM}"
    if code.strip().lower() == "auto assign":
        return "No code - it's assigned automatically."
    return "No public code."


def badge_text(g, b, cd, head="🎖 New TeamSpeak badge"):
    """The message about one badge: its name and description, its code (or why there isn't one), a link to its image."""
    text = f"{head}: [b]{b['name']}[/b]" + (f" – {b['description']}" if b["description"] else "")
    text += "\n" + (code_line(*cd[g]) if g in cd else "No code known yet - I'll send it when it turns up.")
    if b["image"]:
        text += f" · [url={b['image']}_details.svg]image[/url]"
    return text


def save(state):
    write(STATE, state)


def queue(uid, text):
    box = state.setdefault("outbox", {}).setdefault(uid, [])
    if text not in box:
        box.append(text)
    del box[:-30]                                      # someone away for months gets the latest 30


def newest(bl):
    return max(bl, key=lambda k: bl[k]["added"])


def command(e, subs):
    """!badges [subscribe | unsubscribe | latest | forget | help] (the Czech odebirat | zrusit | posledni work too)."""
    word = (e.args.split() or [""])[0].lower()
    uid, name = e.user_uid, e.user_name or "?"
    if not uid:
        return "I can't tell who's asking."
    if word in SUBSCRIBE:
        subs["in"][uid] = name
        subs["out"] = [u for u in subs["out"] if u != uid]
        save_subs(subs)
        return (f"✅ {name}, you're subscribed to new TeamSpeak badges: I'll send you each one privately, with its code "
                "once it's known (if you're offline, you'll get it when you connect). Stop: [b]!badges unsubscribe[/b]")
    if word in UNSUBSCRIBE:
        was = uid in WHO
        subs["in"].pop(uid, None)
        if uid not in subs["out"]:
            subs["out"].append(uid)
        save_subs(subs)
        if state is not None and uid in (state.get("outbox") or {}):
            state["outbox"].pop(uid)                   # what was still waiting for them goes too
            save(state)
        return ("🔕 Done - no more badge messages for you. To get them again: [b]!badges subscribe[/b]" if was
                else "I'm not sending you badges anyway. To get them: [b]!badges subscribe[/b]")
    if word in LATEST:                                 # the newest badge, as an announcement of it looks
        bl, cd = badges(), codes()
        g = newest(bl)
        when = datetime.fromtimestamp(bl[g]["added"], timezone.utc).strftime("%d %b %Y")
        return badge_text(g, bl[g], cd, head=f"🎖 Newest TeamSpeak badge ({when})")
    if word in FORGET:                                 # a real announcement, for whoever asked only
        if uid not in WHO:
            return "You don't get new badges yet - subscribe first: [b]!badges subscribe[/b]"
        if state is None:
            return "I haven't looked at the badges yet - try again in a moment."
        bl, cd = badges(), codes()
        g = newest(bl)
        queue(uid, badge_text(g, bl[g], cd))
        save(state)
        deliver()                                      # the way every announcement goes: by UID, if you're online
        save(state)
        return f"🔁 I forgot I told you about [b]{bl[g]['name']}[/b] - and told you again, just like a new badge."
    on = uid in WHO
    return (("" if word in HELP else f"I don't know '{word}'.\n")
            + "🎖 [b]!badges[/b] - new TeamSpeak badges, privately, with their codes\n"
            + "• [b]!badges subscribe[/b] - send me each new badge\n"
            + "• [b]!badges unsubscribe[/b] - stop\n"
            + "• [b]!badges latest[/b] - the newest badge, now\n"
            + "• [b]!badges forget[/b] - send me the newest one again the way a new one comes (a test)\n"
            + ("You get them privately." if on else "You don't get them yet.")
            + f" {len(WHO)} {'person gets' if len(WHO) == 1 else 'people get'} them.")


def check():
    """Look at both sources: announce what's new (and codes that turned up later), hand over what waits."""
    global state
    bl, cd = badges(), codes()
    if state is None:   # the first check: remember everything, post nothing, say what it watches
        state = {"badges": list(bl), "codes": {g: c for g, (c, _) in cd.items()}}
        save(state)
        n = bl[newest(bl)]
        when = datetime.fromtimestamp(n["added"], timezone.utc).strftime("%d %b %Y")
        return (f"Watching {len(bl)} TeamSpeak badges (and {len(cd)} codes from the forum). Newest: {n['name']} ({when}). "
                + (f"I'll send each new one privately ({len(WHO)}× - whoever's offline gets it when they connect)."
                   if WHO else "I'll post each new one in the channel until someone subscribes.")
                + " Get them privately: [b]!badges subscribe[/b], stop: [b]!badges unsubscribe[/b].")

    seen = set(state["badges"])
    new = sorted((g for g in bl if g not in seen), key=lambda g: bl[g]["added"])
    if len(new) > BURST:
        # More at once than TeamSpeak ever adds (its list changed shape, or what was remembered got lost): the newest
        # one in full and the rest by name - one message, never a flood.
        rest = ", ".join(bl[g]["name"] for g in reversed(new[:-1]))
        more = f"\n…and {len(new) - 1} more new ones: {rest}"
        tell(badge_text(new[-1], bl[new[-1]], cd) + (more if len(more) <= 400 else more[:400].rsplit(",", 1)[0] + ", …"))
        for g in new:
            state["badges"].append(g)
            if g in cd:
                state["codes"][g] = cd[g][0]
        save(state)
        new = []
    for g in new:
        tell(badge_text(g, bl[g], cd))
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
    return ""


state, WHO = None, []


def handle(e):
    """One event: read what's remembered (it may have changed - and a restart loses nothing), then do what was asked."""
    global state, WHO
    state = json.load(open(STATE)) if os.path.exists(STATE) else None
    subs = load_subs()
    WHO = recipients(subs)
    if e.trigger == "command":
        return command(e, subs)
    if e.trigger == "join":                            # nothing new to look for - only hand over what waits for them
        if state is not None and e.user_uid in WHO:
            deliver()
            save(state)
        return ""
    return check()                                     # start | cron | install | manual


ts3bot.serve(handle)
