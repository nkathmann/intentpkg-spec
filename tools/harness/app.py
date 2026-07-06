#!/usr/bin/env python3
"""Mock Beacon Helpdesk — implements helpdesk.intent well enough to exercise
every L3 gate. VIOLATIONS=1 plants six deliberate contract breaches to prove
the runner catches them. TEST_AUTH=1 honors x-test-principal; TEST_HOOKS=1
exposes /__test/jobs/{id}/run and /__test/reset."""
import http.server, os, re, sqlite3, threading, time, urllib.parse
from datetime import datetime, timedelta

DB = os.path.join(os.path.dirname(__file__), 'helpdesk.db')
V = os.environ.get('VIOLATIONS') == '1'

TOK = {"bg":"#FFFFFF","surface":"#FFFFFF","surface-muted":"#F6F8FA","border":"#E3E8EE",
"text":"#1A2233","text-muted":"#5B6676","primary":"#2F6BFF","primary-hover":"#1E54D6",
"primary-soft":"#EAF1FF","success":"#1F9D6B","warning":"#C8791A","danger":"#D64545",
"admin-accent":"#6A3FB5"}

def tint(hexv, t):
    r,g,b = int(hexv[1:3],16), int(hexv[3:5],16), int(hexv[5:7],16)
    mix = lambda c: round(t*c + (1-t)*255)
    return f"#{mix(r):02X}{mix(g):02X}{mix(b):02X}"

def reseed():
    if os.path.exists(DB): os.remove(DB)
    c = sqlite3.connect(DB); x = c.cursor()
    x.executescript("""
    CREATE TABLE app_users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT,
      role TEXT, active INTEGER DEFAULT 1, created TEXT);
    CREATE TABLE specialties(analyst_id INTEGER, category TEXT);
    CREATE TABLE tickets(id INTEGER PRIMARY KEY, subject TEXT, body TEXT, category TEXT,
      status TEXT, creator TEXT, assignee TEXT, unrouted INTEGER DEFAULT 0,
      created TEXT, closed_at TEXT, closed_by TEXT, archived_at TEXT);
    CREATE TABLE messages(id INTEGER PRIMARY KEY, ticket_id INTEGER, author TEXT,
      body TEXT, ts TEXT);
    CREATE TABLE attachments(id INTEGER PRIMARY KEY, message_id INTEGER, filename TEXT, size INTEGER);
    """)
    now = datetime.utcnow()
    users = [("admin","admin-pass-1","administrator"),("user1","user-pass-1","user"),
             ("user2","user-pass-2","user"),("user3","user-pass-3","user"),
             ("hwa1","p","it_analyst"),("hwa2","p","it_analyst"),
             ("swa1","p","it_analyst"),("swa2","p","it_analyst")]
    for u,p,r in users:
        x.execute("INSERT INTO app_users(username,password,role,created) VALUES(?,?,?,?)",(u,p,r,now.isoformat()))
    for a,cat in [("hwa1","hardware"),("hwa2","hardware"),("swa1","software"),("swa2","software")]:
        x.execute("INSERT INTO specialties SELECT id,? FROM app_users WHERE username=?",(cat,a))
    t = lambda h: (now - timedelta(hours=h)).isoformat()
    rows = [
      (1,"Laptop won't dock","Dock stopped working after update.","hardware","OPEN","user1","hwa1",0,t(5),None,None,None),
      (2,"Weird beeping sound","Beeps twice hourly.","other","OPEN","user2","hwa1",1,t(9),None,None,None),
      (3,"IDE crashes on save","Crashes with large files.","software","IN_PROGRESS","user2","swa1",0,t(30),None,None,None),
      (4,"VPN drops every hour","Disconnects on the hour.","software","IN_PROGRESS","user2","swa1",0,t(26),None,None,None),
      (5,"Printer queue stuck","Jobs stuck in queue.","software","CLOSED","user2","swa1",0,t(50),t(2),"user2",None),
      (6,"Old monitor flicker","Flickers on wake.","hardware","CLOSED","user2","hwa2",0,t(80),t(48),"hwa2",None)]
    x.executemany("INSERT INTO tickets VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    msgs = [(1,4,"user2","VPN keeps dropping right on the hour.",t(26)),
            (2,4,"swa1","Looking into the gateway logs now.",t(25)),
            (3,1,"user1","Dock has power but no video.",t(5)),
            (4,5,"user2","Print jobs are stuck again.",t(49)),
            (5,5,"swa1","Cleared the spooler; closing this out.",t(3)),
            (6,6,"user2","Monitor flickers when waking.",t(79)),
            (7,6,"hwa2","Swapped the cable; resolved.",t(49))]
    x.executemany("INSERT INTO messages VALUES(?,?,?,?,?)", msgs)
    x.execute("INSERT INTO attachments VALUES(1,1,'vpn-log.txt',2048)")
    c.commit(); c.close()

def q(sql, args=()):
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    rows = c.execute(sql, args).fetchall(); c.commit(); c.close(); return rows

def q1(sql, args=()):
    r = q(sql, args); return r[0] if r else None

def qi(sql, args=()):
    c = sqlite3.connect(DB); cur = c.execute(sql, args); rid = cur.lastrowid
    c.commit(); c.close(); return rid

CSS = f"""
:root {{ {' '.join(f'--color-{k}: {v};' for k,v in TOK.items())}
  --radius-sm: 6px; --radius-md: 10px; --radius-lg: 16px; --space-unit: 8px;
  --font-family-base: Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }}
* {{ box-sizing: border-box; border-color: var(--color-border); }}
body {{ margin: 0; background: var(--color-bg); color: var(--color-text);
  font-family: var(--font-family-base); font-size: 15px; font-weight: 400; }}
h1 {{ font-size: 28px; font-weight: 600; }} h2 {{ font-size: 18px; font-weight: 600; }}
a {{ color: var(--color-primary-hover); font-weight: 500; }}
small, .meta {{ font-size: 13px; font-weight: 500; color: var(--color-text-muted); }}
button, input, select, textarea {{ font: inherit; color: var(--color-text);
  background: var(--color-surface-muted); border: 1px solid var(--color-border);
  border-radius: var(--radius-md); padding: 8px; }}
.btn-primary {{ background: {('#00B5AD' if V else 'var(--color-primary)')}; color: #FFFFFF; border: 1px solid {('#00B5AD' if V else 'var(--color-primary)')};
  border-radius: var(--radius-md); padding: 8px 16px; font-weight: 500; text-decoration: none; display: inline-block; }}
.btn-secondary {{ background: var(--color-surface); border: 1px solid var(--color-border); color: var(--color-text);
  border-radius: var(--radius-md); padding: 8px 16px; font-weight: 500; text-decoration: none; display: inline-block; }}
.card {{ background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-lg); padding: 24px; }}
header {{ display: flex; justify-content: space-between; align-items: center; padding: 16px 24px;
  border-bottom: 1px solid var(--color-border); height: 64px; }}
main {{ max-width: 1120px; margin: 0 auto; padding: 24px; }}
table {{ border-collapse: collapse; width: 100%; }} th, td {{ text-align: left; padding: 8px; border-bottom: 1px solid var(--color-border); }}
th {{ font-size: 13px; font-weight: 500; color: var(--color-text-muted); }}
.badge {{ font-size: 13px; font-weight: 500; border-radius: var(--radius-sm); padding: 2px 8px; display: inline-block; }}
.b-OPEN {{ background: var(--color-primary-soft); color: var(--color-primary); }}
.b-IN_PROGRESS {{ background: {tint(TOK['warning'],0.12)}; color: var(--color-warning); }}
.b-CLOSED {{ background: {tint(TOK['success'],0.12)}; color: var(--color-success); }}
.b-ARCHIVED {{ background: var(--color-surface-muted); color: var(--color-text-muted); }}
.alert {{ color: var(--color-danger); font-weight: 500; }}
.flag {{ color: var(--color-warning); font-size: 13px; font-weight: 500; }}
.wordmark {{ font-weight: 600; text-decoration: none; color: {('var(--color-admin-accent)' if V else 'var(--color-text)')}; font-size: 18px; }}
.wordmark-admin {{ font-weight: 600; text-decoration: none; color: var(--color-text); font-size: 18px; }}
.accent-bar {{ height: 4px; background: var(--color-admin-accent); position: absolute; top: 0; left: 0; right: 0; }}
.admin-wrap {{ display: flex; }} nav.sidebar {{ width: 240px; padding: 24px; border-right: 1px solid var(--color-border); min-height: 80vh; }}
nav.sidebar a {{ display: block; padding: 8px 0; }}
.menu-btn {{ display: none; }}
article {{ border: 1px solid var(--color-border); border-radius: var(--radius-md); padding: 12px; margin: 8px 0; }}
.avatar {{ display: inline-block; width: 28px; height: 28px; border-radius: 14px; background: #7BC96F; color: #FFFFFF;
  text-align: center; line-height: 28px; font-size: 13px; font-weight: 500; }}
form.compose {{ position: sticky; bottom: 0; background: var(--color-surface); border-top: 1px solid var(--color-border); padding: 12px; }}
@media (max-width: 500px) {{ nav.sidebar {{ display: none; }} .menu-btn {{ display: inline-block; }} }}
"""

def page(title, body, lang_extra=""):
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title>
<style>{CSS}</style></head><body>{body}</body></html>"""

def user_shell(prefix, user, inner, title):
    hdr = f"""<header><a href="/tickets" class="wordmark" data-testid="{prefix}.header.wordmark">Beacon Helpdesk</a>
<button type="button" data-testid="{prefix}.header.user-menu" class="btn-secondary" aria-label="Account menu for {user}">{user}</button></header>"""
    return page(title, hdr + f"<main>{inner}</main>")

ADMIN_NAV = [("users","Users","/admin/users"),("specialties","Specialties","/admin/specialties"),("reports","Archived Reports","/admin/reports/archived")]
def admin_shell(prefix, user, inner, title):
    links = ''.join(f'<a href="{h}" data-testid="{prefix}.nav.{i}-link">{l}</a>' for i,l,h in ADMIN_NAV)
    body = f"""<div class="accent-bar" role="presentation" data-testid="{prefix}.header.accent-bar"></div>
<header style="margin-top:4px"><a href="/admin/users" class="wordmark-admin" data-testid="{prefix}.header.wordmark">Beacon Helpdesk Admin</a>
<button type="button" class="menu-btn btn-secondary" data-testid="{prefix}.header.menu-btn" aria-label="Menu"
 onclick="document.querySelector('[data-region=nav-drawer]').hidden=false">Menu</button></header>
<div class="admin-wrap"><nav class="sidebar" aria-label="Admin">{links}</nav>
<nav data-region="nav-drawer" hidden aria-label="Admin menu">{links.replace('data-testid','data-x')}</nav>
<main>{inner}</main></div>"""
    return page(title, body)

def now(): return datetime.utcnow().isoformat()

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def principal(self):
        if os.environ.get('TEST_AUTH') == '1':
            p = self.headers.get('x-test-principal')
            if p:
                u = q1("SELECT * FROM app_users WHERE username=? AND active=1", (p,))
                return dict(u) if u else None
        ck = self.headers.get('Cookie', '')
        m = re.search(r'sid=([a-z0-9_-]+)', ck)
        if m:
            u = q1("SELECT * FROM app_users WHERE username=? AND active=1", (m.group(1),))
            return dict(u) if u else None
        return None

    def send(self, code, body, hdrs=None):
        b = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(b)))
        for k, v in (hdrs or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(b)

    def redirect(self, loc, cookie=None):
        self.send_response(303); self.send_header('Location', loc)
        if cookie: self.send_header('Set-Cookie', f"sid={cookie}; Path=/")
        self.send_header('Content-Length', '0'); self.end_headers()

    # ------------------------------------------------------------- routes --
    def do_GET(self):
        u = urllib.parse.urlparse(self.path); p, qs = u.path, urllib.parse.parse_qs(u.query)
        me = self.principal()
        if p == '/': return self.redirect('/admin/users' if me and me['role']=='administrator' else ('/tickets' if me else '/login'))
        if p == '/login': return self.login_page()
        if not me: return self.redirect('/login')
        if p == '/tickets': return self.ticket_list(me, qs)
        if p == '/tickets/new': return self.ticket_new(me)
        m = re.match(r'/tickets/(\d+)/close$', p)
        if m: return self.close_ticket(me, int(m.group(1)))
        m = re.match(r'/tickets/(\d+)$', p)
        if m: return self.ticket_detail(me, int(m.group(1)))
        m = re.match(r'/api/attachments/(\d+)$', p)
        if m: return self.send(200, 'attachment-bytes')
        if p.startswith('/admin'):
            if me['role'] != 'administrator': return self.send(404, page('Not found','<main><h1>Not found</h1></main>'))
            if p == '/admin/users': return self.admin_users(me, qs)
            m = re.match(r'/admin/users/(\d+)/toggle$', p)
            if m:
                q("UPDATE app_users SET active = 1-active WHERE id=?", (int(m.group(1)),))
                return self.redirect('/admin/users')
            if p == '/admin/specialties': return self.admin_specialties(me)
            if p == '/admin/reports/archived': return self.admin_reports(me)
        self.send(404, page('Not found','<main><h1>Not found</h1></main>'))

    def do_POST(self):
        u = urllib.parse.urlparse(self.path); p = u.path
        ln = int(self.headers.get('Content-Length') or 0)
        form = urllib.parse.parse_qs(self.rfile.read(ln).decode()) if ln else {}
        f = lambda k: form.get(k, [''])[0]
        if p == '/__test/reset' and os.environ.get('TEST_HOOKS') == '1':
            reseed(); return self.send(200, 'ok')
        if p == '/__test/jobs/archive-closed/run' and os.environ.get('TEST_HOOKS') == '1':
            cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
            q("UPDATE tickets SET status='ARCHIVED', archived_at=? WHERE status='CLOSED' AND closed_at <= ?", (now(), cutoff))
            return self.send(200, 'ok')
        if p == '/login':
            u_ = q1("SELECT * FROM app_users WHERE username=? AND active=1", (f('username'),))
            if not u_ or u_['password'] != f('password'):
                return self.login_page(error=True, username=f('username'))
            return self.redirect('/admin/users' if u_['role']=='administrator' else '/tickets', cookie=u_['username'])
        me = self.principal()
        if not me: return self.redirect('/login')
        if p == '/tickets':
            cat = f('category')
            an = q1("""SELECT u.username FROM app_users u JOIN specialties s ON s.analyst_id=u.id
                       WHERE s.category=? AND u.active=1 ORDER BY
                       (SELECT COUNT(*) FROM tickets t WHERE t.assignee=u.username AND t.status IN ('OPEN','IN_PROGRESS')) LIMIT 1""", (cat,))
            unrouted = 0
            if not an:
                an = q1("""SELECT username FROM app_users WHERE role='it_analyst' AND active=1 ORDER BY
                        (SELECT COUNT(*) FROM tickets t WHERE t.assignee=users.username AND t.status IN ('OPEN','IN_PROGRESS')) LIMIT 1""")
                unrouted = 1
            tid = qi("INSERT INTO tickets(subject,body,category,status,creator,assignee,unrouted,created) VALUES(?,?,?,?,?,?,?,?)",
              (f('subject'), f('body'), cat, 'OPEN', me['username'], an['username'], unrouted, now()))
            return self.redirect(f'/tickets/{tid}')
        m = re.match(r'/tickets/(\d+)/messages$', p)
        if m:
            tid = int(m.group(1)); t = q1("SELECT * FROM tickets WHERE id=?", (tid,))
            if not t or me['username'] not in (t['creator'], t['assignee']): return self.send(404, 'nf')
            if t['status'] in ('CLOSED','ARCHIVED'): return self.send(409, 'closed')
            q("INSERT INTO messages(ticket_id,author,body,ts) VALUES(?,?,?,?)", (tid, me['username'], f('body'), now()))
            if t['status']=='OPEN' and me['role']=='it_analyst':
                q("UPDATE tickets SET status='IN_PROGRESS' WHERE id=?", (tid,))
            return self.redirect(f'/tickets/{tid}')
        if p == '/admin/users' and me['role']=='administrator':
            if q1("SELECT 1 AS x FROM app_users WHERE username=?", (f('username'),)):
                return self.admin_users(me, {'create':['1']}, error=True)
            q("INSERT INTO app_users(username,password,role,created) VALUES(?,?,?,?)", (f('username'), f('password'), f('role'), now()))
            return self.redirect('/admin/users')
        m = re.match(r'/admin/specialties/(\d+)$', p)
        if m and me['role']=='administrator':
            q("DELETE FROM specialties WHERE analyst_id=?", (int(m.group(1)),))
            for cat in form.get('cats', []):
                q("INSERT INTO specialties VALUES(?,?)", (int(m.group(1)), cat))
            return self.redirect('/admin/specialties')
        self.send(404, 'nf')

    # -------------------------------------------------------------- pages --
    def login_page(self, error=False, username=''):
        fields = f"""<label for="u">Username</label><br>
<input id="u" data-testid="login.main.username-input" name="username" type="text" value="{username}"><br>
<label for="pw">Password</label><br>
<input id="pw" data-testid="login.main.password-input" name="password" type="password"><br>"""
        if V:  # violation 6: swapped DOM focus order
            fields = fields.replace('<label for="u">','\x00').replace('<label for="pw">','<label for="u">').replace('\x00','<label for="pw">')
            fields = f"""<label for="pw">Password</label><br>
<input id="pw" data-testid="login.main.password-input" name="password" type="password"><br>
<label for="u">Username</label><br>
<input id="u" data-testid="login.main.username-input" name="username" type="text" value="{username}"><br>"""
        err = f'<p role="alert" class="alert" data-testid="login.main.error">That username or password didn&#39;t work. Try again.</p>' if error else ''
        tagline = '' if V else '<p data-testid="login.main.tagline">Signal sent. Help on the way.</p>'  # violation 1
        body = f"""<main><div style="max-width:380px;margin:10vh auto;text-align:center">
<h1 data-testid="login.main.wordmark">Beacon Helpdesk</h1>{tagline}
<form class="card" method="post" action="/login" data-testid="login.main.card" style="text-align:left">
{err}{fields}<button type="submit" class="btn-primary" data-testid="login.main.submit-btn">Sign In</button>
</form></div></main>"""
        self.send(200, page('Sign in — Beacon Helpdesk', body))

    def ticket_list(self, me, qs):
        st = (qs.get('status') or ['all'])[0]
        cond, extra = ("", ()) if st == 'all' else (" AND status=?", (st,))
        base_excl = "" if st == 'ARCHIVED' else " AND status!='ARCHIVED'"
        who = "assignee" if me['role'] == 'it_analyst' else "creator"
        rows = q(f"SELECT * FROM tickets WHERE {who}=?{base_excl}{cond} ORDER BY created DESC",
                 (me['username'],) + extra)
        empty = ("Nothing assigned right now." if me['role'] == 'it_analyst'
                 else "No tickets yet. Create one when something needs attention.")
        tabs = ''.join(f'<a role="tab" data-testid="ticket-list.main.status-filter.tab" href="/tickets?status={s}">{s}</a> ' for s in ['all','OPEN','IN_PROGRESS','CLOSED','ARCHIVED'])
        newbtn = ('<a role="button" class="btn-primary" href="/tickets/new" data-testid="ticket-list.header.new-ticket-btn">New Ticket</a>'
                  if me['role'] == 'user' else '')
        if rows:
            trs = ''.join(f"""<tr data-testid="ticket-list.main.row"><td><a href="/tickets/{r['id']}" data-testid="ticket-list.main.row.subject-link">{r['subject']}</a></td>
<td><span class="badge b-{r['status']}" role="status" data-testid="ticket-list.main.row.status-badge">{r['status']}</span>
{('<span class="flag" role="status" data-testid="ticket-list.main.row.unrouted-flag">unrouted</span>' if r['unrouted'] else '')}</td>
<td class="meta">{r['category']}</td><td class="meta">{r['created'][:16]}</td></tr>""" for r in rows)
            content = f'<table><thead><tr><th>Subject</th><th>Status</th><th>Category</th><th>Last activity</th></tr></thead><tbody>{trs}</tbody></table>'
        else:
            content = f'<div class="card" style="text-align:center"><p data-testid="ticket-list.main.empty">{empty}</p></div>'
        inner = f"""<div style="display:flex;justify-content:space-between;align-items:center"><h1>Tickets</h1>{newbtn}</div>
<div role="tablist" data-testid="ticket-list.main.status-filter" class="meta">{tabs}</div>{content}"""
        self.send(200, user_shell('ticket-list', me['username'], inner, 'Tickets — Beacon Helpdesk'))

    def ticket_new(self, me):
        opts = ''.join(f'<option value="{c}">{c}</option>' for c in ['hardware','software','network','access','other'])
        inner = f"""<h1>New Ticket</h1><form class="card" method="post" action="/tickets">
<label for="s">Subject</label><br><input id="s" name="subject" type="text" data-testid="ticket-create.main.subject-input"><br>
<label for="b">Details</label><br><textarea id="b" name="body" data-testid="ticket-create.main.body-input"></textarea><br>
<label for="c">Category</label><br><select id="c" name="category" data-testid="ticket-create.main.category-select">{opts}</select><br>
<button type="submit" class="btn-primary" data-testid="ticket-create.main.submit-btn">Create Ticket</button></form>"""
        self.send(200, user_shell('ticket-create', me['username'], inner, 'New Ticket — Beacon Helpdesk'))

    def ticket_detail(self, me, tid):
        t = q1("SELECT * FROM tickets WHERE id=?", (tid,))
        if not t or (me['role'] != 'administrator' and me['username'] not in (t['creator'], t['assignee'])):
            return self.send(404, page('Not found','<main><h1>Not found</h1></main>'))
        open_ = t['status'] in ('OPEN','IN_PROGRESS')
        msgs = q("SELECT m.*, (SELECT COUNT(*) FROM attachments a WHERE a.message_id=m.id) AS nat FROM messages m WHERE ticket_id=? ORDER BY ts", (tid,))
        arts = ''
        for m in msgs:
            att = q1("SELECT * FROM attachments WHERE message_id=?", (m['id'],)) if m['nat'] else None
            attl = (f'<br><a data-testid="ticket-detail.thread.message.attachment" href="/api/attachments/{att["id"]}">{att["filename"]} <small>({att["size"]} B)</small></a>' if att else '')
            arts += f"""<article data-testid="ticket-detail.thread.message" data-ts="{m['ts']}">
<span class="avatar" role="img" aria-label="{m['author']}" data-testid="ticket-detail.thread.message.avatar">{m['author'][:2]}</span>
<span style="font-weight:500">{m['author']}</span> <small>{m['ts'][:16]}</small><p>{m['body']}</p>{attl}</article>"""
        closedcopy = "Ticket closed — thanks!" if V else "This ticket is closed."   # violation 3
        banner = ''
        if t['status'] == 'CLOSED':
            banner = f'<p role="status" class="meta" data-testid="ticket-detail.ticket-header.closed-banner">{closedcopy}</p>'
        if t['status'] == 'ARCHIVED':
            banner = '<p role="status" class="meta" data-testid="ticket-detail.ticket-header.archived-banner">This ticket is archived and read-only.</p>'
        onclick = ' onclick="return confirm(\'Really close this ticket?\')"' if V else ''   # violation 4
        closebtn = (f'<a role="button" class="btn-secondary" href="/tickets/{tid}/close"{onclick} data-testid="ticket-detail.ticket-header.close-btn">Close Ticket</a>'
                    if open_ and me['username'] in (t['creator'], t['assignee']) else '')
        compose = (f"""<form class="compose" method="post" action="/tickets/{tid}/messages">
<label for="mb" class="meta">Reply</label><br>
<textarea id="mb" name="body" data-testid="ticket-detail.compose.body-input"></textarea>
<button type="button" class="btn-secondary" data-testid="ticket-detail.compose.attach-input">Attach file</button>
<button type="submit" class="btn-primary" data-testid="ticket-detail.compose.send-btn">Send</button></form>""" if open_ else '')
        inner = f"""<section aria-label="Ticket summary">
<h1 data-testid="ticket-detail.ticket-header.subject">{t['subject']}</h1>
<span class="badge b-{t['status']}" role="status" data-testid="ticket-detail.ticket-header.status-badge">{t['status']}</span>
<span class="meta" data-testid="ticket-detail.ticket-header.category">{t['category']}</span>
<span class="meta" data-testid="ticket-detail.ticket-header.creator">Opened by {t['creator']}</span>
<span class="meta" data-testid="ticket-detail.ticket-header.assignee">Assigned to {t['assignee'] or ''}</span>
{banner}{closebtn}</section>"""
        hdr = f"""<header><a href="/tickets" class="wordmark" data-testid="ticket-detail.header.wordmark">Beacon Helpdesk</a>
<button type="button" data-testid="ticket-detail.header.user-menu" class="btn-secondary" aria-label="Account menu for {me['username']}">{me['username']}</button></header>"""
        wrap = f'{hdr}<div style="max-width:1120px;margin:0 auto;padding:24px">{inner}</div><main>{arts or "<p class=meta>No messages yet.</p>"}</main>{compose}'
        self.send(200, page(f"{t['subject']} — Beacon Helpdesk", wrap))

    def close_ticket(self, me, tid):
        t = q1("SELECT * FROM tickets WHERE id=?", (tid,))
        if not t or me['username'] not in (t['creator'], t['assignee']): return self.send(404, 'nf')
        if t['status'] in ('OPEN','IN_PROGRESS'):
            q("UPDATE tickets SET status='CLOSED', closed_at=?, closed_by=? WHERE id=?", (now(), me['username'], tid))
        return self.redirect(f'/tickets/{tid}')

    def admin_users(self, me, qs, error=False):
        rows = q("SELECT * FROM app_users ORDER BY id")
        trs = ''.join(f"""<tr data-testid="admin-users.main.user-table.row"><td>{r['username']}</td><td>{r['role']}</td>
<td><span class="badge {'b-OPEN' if r['active'] else 'b-ARCHIVED'}" role="status">{'active' if r['active'] else 'disabled'}</span></td>
<td class="meta">{r['created'][:10]}</td>
<td><a role="button" class="btn-secondary" href="/admin/users/{r['id']}/toggle" data-testid="admin-users.main.user-table.row.toggle-active">{'Disable' if r['active'] else 'Enable'}</a></td></tr>""" for r in rows)
        create = ''
        if qs.get('create'):
            err = '<p role="alert" class="alert" data-testid="admin-users.main.create-form.error">That username is already taken.</p>' if error else ''
            ropts = ''.join(f'<option value="{r}">{r}</option>' for r in ['user','it_analyst','administrator'])
            create = f"""<form class="card" method="post" action="/admin/users">{err}
<label for="nu">Username</label><br><input id="nu" name="username" type="text" data-testid="admin-users.main.create-form.username-input"><br>
<label for="np">Password</label><br><input id="np" name="password" type="password" data-testid="admin-users.main.create-form.password-input"><br>
<label for="nr">Role</label><br><select id="nr" name="role" data-testid="admin-users.main.create-form.role-select">{ropts}</select><br>
<button type="submit" class="btn-primary" data-testid="admin-users.main.create-form.submit-btn">Create</button></form>"""
        inner = f"""<div style="display:flex;justify-content:space-between;align-items:center"><h1>Users</h1>
<a role="button" class="btn-primary" href="/admin/users?create=1" data-testid="admin-users.main.create-btn">Create User</a></div>
{create}<table data-testid="admin-users.main.user-table"><thead><tr><th>Username</th><th>Role</th><th>Status</th><th>Created</th><th></th></tr></thead><tbody>{trs}</tbody></table>"""
        self.send(200, admin_shell('admin-users', me['username'], inner, 'Users — Beacon Admin'))

    def admin_specialties(self, me):
        analysts = q("SELECT * FROM app_users WHERE role='it_analyst' ORDER BY username")
        lis = ''
        for a in analysts:
            have = {r['category'] for r in q("SELECT category FROM specialties WHERE analyst_id=?", (a['id'],))}
            chips = ''.join(f'<label><input type="checkbox" name="cats" value="{c}" {"checked" if c in have else ""}>{c}</label> '
                            for c in ['hardware','software','network','access','other'])
            lis += f"""<li data-testid="admin-specialties.main.analyst-row"><form method="post" action="/admin/specialties/{a['id']}">
<span style="font-weight:500">{a['username']}</span>
<fieldset data-testid="admin-specialties.main.analyst-row.specialty-chips"><legend class="meta">Specialties</legend>{chips}</fieldset>
<button type="submit" class="btn-primary" data-testid="admin-specialties.main.analyst-row.save-btn">Save</button></form></li>"""
        inner = f'<h1>Specialties</h1><ul data-testid="admin-specialties.main.analyst-list" style="list-style:none;padding:0">{lis}</ul>'
        self.send(200, admin_shell('admin-specialties', me['username'], inner, 'Specialties — Beacon Admin'))

    def admin_reports(self, me):
        rows = q("SELECT * FROM tickets WHERE status='ARCHIVED' ORDER BY archived_at DESC")
        if rows:
            trs = ''.join(f"""<tr data-testid="admin-reports.main.archived-table.row"><td>{r['subject']}</td><td class="meta">{r['category']}</td>
<td>{r['creator']}</td><td>{r['assignee']}</td><td class="meta">{(r['closed_at'] or '')[:10]}</td><td class="meta">{(r['archived_at'] or '')[:10]}</td></tr>""" for r in rows)
            content = f"""<div role="group" data-testid="admin-reports.main.filters" class="meta">
<label for="fc">Category</label> <select id="fc"><option value="all">all</option></select></div>
<p role="status" data-testid="admin-reports.main.count-summary">{len(rows)} archived ticket{'s' if len(rows)!=1 else ''}</p>
<table data-testid="admin-reports.main.archived-table"><thead><tr><th>Subject</th><th>Category</th><th>Creator</th><th>Assignee</th><th>Closed</th><th>Archived</th></tr></thead><tbody>{trs}</tbody></table>"""
        else:
            content = '<div class="card" style="text-align:center"><p data-testid="admin-reports.main.empty">No archived tickets yet. Closed tickets archive automatically after 24 hours.</p></div>'
        inner = f'<h1>Archived Reports</h1>{content}'
        self.send(200, admin_shell('admin-reports', me['username'], inner, 'Archived Reports — Beacon Admin'))

if __name__ == '__main__':
    reseed()
    port = int(os.environ.get('PORT', 8787))
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', port), H)
    print(f"beacon mock on :{port} violations={V}")
    srv.serve_forever()
