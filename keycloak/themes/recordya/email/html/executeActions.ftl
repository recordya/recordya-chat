<html>
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
</head>
<body style="margin:0; padding:0; background:#f9f9f9; font-family:'Inter',system-ui,-apple-system,sans-serif; -webkit-font-smoothing:antialiased;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f9f9f9; padding:40px 16px;">
        <tr>
            <td align="center">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:480px; background:#ffffff; border:1px solid #e5e5e5; border-radius:12px; overflow:hidden;">
                    <!-- Title -->
                    <tr>
                        <td style="padding:32px 32px 0; text-align:center;">
                            <h1 style="margin:0; font-size:22px; font-weight:600; color:#0a0a0a; letter-spacing:-0.025em;">${msg("rdyExecuteActionsTitle")}</h1>
                        </td>
                    </tr>
                    <!-- Body -->
                    <tr>
                        <td style="padding:16px 32px 0; font-size:14px; line-height:1.6; color:#737373;">
                            <p style="margin:0;">${msg("rdyEmailGreeting")}</p>
                            <p style="margin:12px 0 0;">${msg("rdyExecuteActionsLine1")}</p>
                            <p style="margin:12px 0 0;">${msg("rdyExecuteActionsLine2Html")}</p>
                        </td>
                    </tr>
                    <!-- CTA Button -->
                    <tr>
                        <td style="padding:24px 32px;" align="center">
                            <a href="${link}" target="_blank" style="display:inline-block; padding:12px 32px; background:#171717; color:#fafafa; font-size:14px; font-weight:500; text-decoration:none; border-radius:10px;">${msg("rdyExecuteActionsButton")}</a>
                        </td>
                    </tr>
                    <!-- Expiration notice -->
                    <tr>
                        <td style="padding:0 32px; font-size:13px; color:#a3a3a3; text-align:center;">
                            <p style="margin:0;">${msg("rdyLinkExpiration", linkExpirationFormatter(linkExpiration))}</p>
                        </td>
                    </tr>
                    <!-- Fallback link -->
                    <tr>
                        <td style="padding:16px 32px 32px; font-size:12px; color:#a3a3a3; word-break:break-all;">
                            <p style="margin:0;">${msg("rdyFallbackIntro")}</p>
                            <p style="margin:4px 0 0;"><a href="${link}" style="color:#737373;">${link}</a></p>
                        </td>
                    </tr>
                    <!-- Footer -->
                    <tr>
                        <td style="padding:16px 32px; border-top:1px solid #e5e5e5; text-align:center; font-size:12px; color:#a3a3a3;">
                            <p style="margin:0;">&copy; Recordya</p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
