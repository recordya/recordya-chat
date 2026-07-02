<!DOCTYPE html>
<html lang="${locale.currentLanguageTag}">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="robots" content="noindex, nofollow" />
    <title>${msg("rdyUpdatePasswordTitle")}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet" />
    <style>
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

        body {
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            background: hsl(0 0% 98%);
            color: hsl(0 0% 3.9%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 1rem;
            -webkit-font-smoothing: antialiased;
        }

        .card {
            width: 100%;
            background: #fff;
            border: 1px solid hsl(0 0% 89.8%);
            border-radius: 0.75rem;
            box-shadow: 0 1px 2px 0 rgb(0 0 0 / 0.05);
            padding: 1.5rem;
        }

        .card-header { text-align: center; padding-bottom: 1.5rem; }
        .card-title { font-size: 1.5rem; font-weight: 600; line-height: 1; letter-spacing: -0.025em; color: hsl(0 0% 3.9%); }
        .card-description { font-size: 0.875rem; color: hsl(0 0% 45.1%); margin-top: 0.375rem; }
        .card-content { display: flex; flex-direction: column; gap: 1rem; }

        .field { display: flex; flex-direction: column; gap: 0.5rem; }
        label { font-size: 0.875rem; font-weight: 500; line-height: 1; color: hsl(0 0% 3.9%); }

        input[type="password"] {
            height: 2.5rem;
            width: 100%;
            border: 1px solid hsl(0 0% 89.8%);
            border-radius: calc(0.75rem - 2px);
            background: transparent;
            padding: 0.5rem 0.75rem;
            font-family: inherit;
            font-size: 0.875rem;
            color: hsl(0 0% 3.9%);
            outline: none;
            transition: border-color 0.15s, box-shadow 0.15s;
        }

        input::placeholder { color: hsl(0 0% 45.1%); }
        input:focus { border-color: hsl(0 0% 13%); box-shadow: 0 0 0 2px hsl(0 0% 13% / 0.08); }

        .card-footer { padding-top: 1.5rem; display: flex; flex-direction: column; gap: 0.75rem; }

        .btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 100%;
            height: 2.5rem;
            background: hsl(0 0% 9%);
            color: hsl(0 0% 98%);
            border: none;
            border-radius: calc(0.75rem - 2px);
            font-family: inherit;
            font-size: 0.875rem;
            font-weight: 500;
            cursor: pointer;
            transition: background 0.15s;
            text-decoration: none;
        }

        .btn:hover { background: hsl(0 0% 15%); }

        .alert {
            background: hsl(0 84% 95%);
            color: hsl(0 84% 40%);
            border: 1px solid hsl(0 84% 85%);
            border-radius: calc(0.75rem - 2px);
            padding: 0.75rem 1rem;
            font-size: 0.875rem;
            margin-bottom: 1rem;
        }

        .wrapper { display: flex; flex-direction: column; align-items: center; width: 100%; max-width: 28rem; }
        .branding { display: flex; align-items: center; justify-content: center; gap: 0.375rem; margin-top: 1.5rem; }
        .branding span { font-size: 0.75rem; color: hsl(0 0% 45.1% / 0.6); }
        .branding a { transition: opacity 0.15s; }
        .branding a:hover { opacity: 0.8; }
        .branding img { height: 1.5rem; display: block; }
    </style>
</head>
<body>
    <div class="wrapper">
        <div class="card">
            <div class="card-header">
                <h1 class="card-title">${msg("rdyUpdatePasswordTitle")}</h1>
                <p class="card-description">${msg("rdyUpdatePasswordDescription")}</p>
            </div>

            <#if message?has_content && (message.type == 'error' || message.type == 'warning')>
                <div class="alert">${kcSanitize(message.summary)}</div>
            </#if>

            <form class="card-content" action="${url.loginAction}" method="post">
                <div class="field">
                    <label for="password-new">${msg("rdyNewPasswordLabel")}</label>
                    <input id="password-new" name="password-new" type="password"
                           placeholder="••••••••"
                           autofocus autocomplete="new-password" />
                </div>
                <div class="field">
                    <label for="password-confirm">${msg("rdyConfirmPasswordLabel")}</label>
                    <input id="password-confirm" name="password-confirm" type="password"
                           placeholder="••••••••"
                           autocomplete="new-password" />
                </div>
                <input type="hidden" id="username" name="username" value="${(username!'')}" />
                <div class="card-footer">
                    <button class="btn" type="submit">${msg("rdySavePassword")}</button>
                </div>
            </form>
        </div>

        <div class="branding">
            <span>${msg("rdyPoweredBy")}</span>
            <a href="https://recordya.ai" target="_blank" rel="noopener noreferrer">
                <img src="${url.resourcesPath}/img/recordya-logo.png" alt="Recordya" />
            </a>
        </div>
    </div>
</body>
</html>
