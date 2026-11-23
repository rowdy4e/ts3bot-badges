# ts3bot-badges

Plugin pro TeamSpeak bota. Hlídá TeamSpeak badges: každou novou napíše soukromě těm, kdo ji odebírají (podle UID, ne
jména) - kdo není online, dostane ji, až se připojí. Kód k badge pošle, jakmile je známý (oficiální seznam + vlákno
na fóru). Když nikdo neodebírá, píše do kanálu.

## Instalace

Soukromá zpráva botovi:

```
!service install github.com/rowdy4e/ts3bot-badges
```

Bot ukáže, co plugin dělá a co smí, a nainstaluje ho až po tvém „ano“.

## Odběr

```
!badges subscribe     nové badges mi piš soukromě
!badges unsubscribe   už mi je nepiš
!badges               jestli je odebírám
```

Admini můžou hned. Aby se mohl přihlásit kdokoli, admin příkaz zveřejní: `!service public badges on` - a lidé
potřebují oprávnění spouštět zveřejněné příkazy služeb (`!perms * skills` pro všechny).

Admin může lidi přidat i sám: `!service install github.com/rowdy4e/ts3bot-badges notify=me,Tisi`, později
`!service set badges notify …` (me = ty; jméno jen admina, jinak UID). Kdo napíše `!badges unsubscribe`, nedostane nic,
ani když ho admin přidal.

Jak plugin napsat: [ts3bot-plugin-template](https://github.com/rowdy4e/ts3bot-plugin-template).
