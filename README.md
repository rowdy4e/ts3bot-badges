# ts3bot-badges

A plugin for the TeamSpeak bot. It watches TeamSpeak badges and sends each new one privately to whoever subscribed
(by UID, not by name) - whoever is offline gets it when they connect. It adds the redeem code as soon as it's known
(the official badge list + the forum thread). When nobody has subscribed, it posts to the channel.

## Install

Send the bot a private message:

```
!service install github.com/rowdy4e/ts3bot-badges
```

The bot shows what the plugin does and what it may do, and installs it only after you reply "yes".

## Subscribing

```
!badges subscribe     send me new badges privately
!badges unsubscribe   stop sending them to me
!badges latest        the newest badge, with its code
!badges forget        send me the newest one again the way a new one comes (a test, only for you)
!badges               help, and whether I get them
```

Admins can use it right away. To let anyone subscribe, an admin publishes the command - `!service public badges on` -
and people need the right to run published service commands (`!perms * skills` for everyone).

An admin can also add people: `!service install github.com/rowdy4e/ts3bot-badges notify=me,Tisi`, later
`!service set badges notify …` (me = you; a name only for an admin, otherwise a UID). Whoever types
`!badges unsubscribe` gets nothing, even when an admin added them.

How to write a plugin: [ts3bot-plugin-template](https://github.com/rowdy4e/ts3bot-plugin-template).
