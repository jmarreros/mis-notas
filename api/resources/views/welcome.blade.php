<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="robots" content="noindex, nofollow">
    <title>Mis Notas</title>
    <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Crect x='2' y='2' width='96' height='96' rx='22' fill='%231F6B45'/%3E%3Cpath d='M29 20h31l15 15v43a2 2 0 0 1-2 2H29a2 2 0 0 1-2-2V22a2 2 0 0 1 2-2z' fill='%23fff'/%3E%3Cpath d='M35 20h11v22l-5.5-4.5L35 42z' fill='%23FF5500'/%3E%3C/svg%3E">
    <style>
        :root {
            --bg: #111111;
            --card: #161616;
            --border: #222222;
            --text: #E6E6E6;
            --muted: #888888;
            --soft: #A0A0A0;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 24px;
            background: var(--bg);
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
            -webkit-font-smoothing: antialiased;
        }
        main {
            width: 100%;
            max-width: 440px;
            padding: 48px 36px 36px;
            text-align: center;
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 20px;
            box-shadow: 0 24px 60px rgba(0, 0, 0, .45);
        }
        .logo { width: 96px; height: 96px; margin-bottom: 24px; filter: drop-shadow(0 6px 14px rgba(0, 0, 0, .5)); }
        h1 { font-size: 30px; font-weight: 700; letter-spacing: .01em; margin-bottom: 12px; }
        p { font-size: 15px; line-height: 1.6; color: var(--soft); }
        .lines { display: flex; flex-direction: column; gap: 8px; align-items: center; margin: 28px 0 24px; }
        .lines span { display: block; height: 4px; border-radius: 2px; background: #222; }
        .lines span:nth-child(1) { width: 62%; }
        .lines span:nth-child(2) { width: 76%; }
        .lines span:nth-child(3) { width: 42%; }
        footer { font-size: 12px; color: var(--muted); }
    </style>
</head>
<body>
    <main>
        <svg class="logo" viewBox="0 0 100 100" role="img" aria-label="Mis Notas">
            <defs>
                <linearGradient id="tile" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0" stop-color="#2F9462"/>
                    <stop offset=".55" stop-color="#1F6B45"/>
                    <stop offset="1" stop-color="#13472D"/>
                </linearGradient>
                <linearGradient id="mark" x1="0" y1="0" x2="1" y2="1">
                    <stop offset="0" stop-color="#D4006C"/>
                    <stop offset=".5" stop-color="#FF5500"/>
                    <stop offset="1" stop-color="#FFB800"/>
                </linearGradient>
            </defs>
            <rect x="2" y="2" width="96" height="96" rx="22" fill="url(#tile)"/>
            <rect x="2.5" y="2.5" width="95" height="95" rx="21.5" fill="none" stroke="#fff" stroke-opacity=".18"/>
            <path d="M29 20h31l15 15v43a2 2 0 0 1-2 2H29a2 2 0 0 1-2-2V22a2 2 0 0 1 2-2z" fill="#fff"/>
            <path d="M60 20v13a2 2 0 0 0 2 2h13z" fill="#CCCCCC"/>
            <path d="M35 20h11v22l-5.5-4.5L35 42z" fill="url(#mark)"/>
            <g fill="#0E3B25">
                <rect x="35" y="50" width="30" height="4" rx="1"/>
                <rect x="35" y="59" width="34" height="4" rx="1"/>
                <rect x="35" y="68" width="20" height="4" rx="1"/>
            </g>
        </svg>
        <h1>Mis Notas</h1>
        <p>Tus notas, siempre contigo y al día en todos tus dispositivos.</p>
        <div class="lines" aria-hidden="true"><span></span><span></span><span></span></div>
        <p>Este es el espacio privado donde se guardan y sincronizan tus notas. Abre la aplicación Mis Notas para escribir, organizar y consultarlas.</p>
        <footer style="margin-top: 28px;">Acceso exclusivo para usuarios autorizados.</footer>
    </main>
</body>
</html>
