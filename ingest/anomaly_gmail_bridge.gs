/**
 * KL anomaly → Gmail bridge (no Resend / no SMTP from Railway).
 *
 * Railway blocks outbound SMTP to Gmail. This Apps Script receives an HTTPS
 * POST from ingest and sends mail via your Google account (MailApp).
 *
 * Setup (once, ~2 min):
 * 1. https://script.google.com → New project
 * 2. Paste this file as Code.gs
 * 3. Project Settings → Script properties → add:
 *      WEBHOOK_TOKEN = (optional shared secret; same as ANOMALY_EMAIL_WEBHOOK_TOKEN)
 * 4. Deploy → New deployment → Type: Web app
 *      Execute as: Me
 *      Who has access: Anyone  (Railway has no Google login; token protects it)
 * 5. Copy the Web app URL → Railway ingest:
 *      ANOMALY_EMAIL_WEBHOOK_URL=<web app url>
 *      ANOMALY_NOTIFY_EMAIL=mathoreashutosh23@gmail.com
 *      ANOMALY_EMAIL_WEBHOOK_TOKEN=<same as WEBHOOK_TOKEN if set>
 * 6. Redeploy ingest (or wait for next deploy), then:
 *      python -m ingest.anomaly --notify-test
 */

function doPost(e) {
  var props = PropertiesService.getScriptProperties();
  var expected = props.getProperty('WEBHOOK_TOKEN') || '';

  var raw = (e && e.postData && e.postData.contents) ? e.postData.contents : '';
  var data;
  try {
    data = JSON.parse(raw);
  } catch (err) {
    return _json({ ok: false, error: 'invalid json' }, 400);
  }

  if (expected && data.token !== expected) {
    return _json({ ok: false, error: 'unauthorized' }, 401);
  }

  var to = data.to || props.getProperty('DEFAULT_TO') || Session.getActiveUser().getEmail();
  var subject = data.subject || '[KL] anomaly';
  var body = data.text || data.body || '';
  if (!to || !body) {
    return _json({ ok: false, error: 'missing to or text' }, 400);
  }

  MailApp.sendEmail({
    to: to,
    subject: subject,
    body: body,
  });

  return _json({ ok: true, event_key: data.event_key || null });
}

function doGet() {
  return _json({ ok: true, service: 'kardashev-anomaly-gmail-bridge' });
}

function _json(obj, status) {
  var out = ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
  // Apps Script web apps ignore HTTP status for most clients; body.ok is the signal.
  return out;
}
