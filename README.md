# ts3bot-badges

Plugin pro TeamSpeak bota. Hlídá TeamSpeak badges: každou novou ohlásí do kanálu, nebo soukromě vybraným lidem (podle UID, ne jména) - kdo není online, dostane to, až se připojí. Kód k badge pošle, jakmile je známý (oficiální seznam + vlákno na fóru).

## Instalace

Soukromá zpráva botovi:

```
!service install github.com/rowdy4e/ts3bot-badges notify=me,Tisi
```

Bot ukáže, co plugin dělá a co smí, a nainstaluje ho až po tvém „ano“.
`notify=me,Tisi` = komu psát (me = ty; jméno jen admina, jinak UID). Změnit jde i později: `!service set badges notify me`.

Jak plugin napsat: [ts3bot-plugin-template](https://github.com/rowdy4e/ts3bot-plugin-template).
