#!/usr/bin/env python3
#!/usr/bin/env python3
import click
import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path.home() / ".legacy_saas_exit.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS industries
                 (id INTEGER PRIMARY KEY, name TEXT UNIQUE, tech_capability TEXT, notes TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS partners
                 (id INTEGER PRIMARY KEY, company TEXT, ceo_name TEXT, industry_id INTEGER,
                  relationship_start DATE, last_contact DATE, trust_level INTEGER, notes TEXT,
                  FOREIGN KEY(industry_id) REFERENCES industries(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS interactions
                 (id INTEGER PRIMARY KEY, partner_id INTEGER, date DATE, type TEXT, summary TEXT,
                  FOREIGN KEY(partner_id) REFERENCES partners(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS opportunities
                 (id INTEGER PRIMARY KEY, partner_id INTEGER, type TEXT, status TEXT, 
                  value_estimate INTEGER, notes TEXT, created_date DATE,
                  FOREIGN KEY(partner_id) REFERENCES partners(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS funding
                 (id INTEGER PRIMARY KEY, amount INTEGER, date DATE, purpose TEXT, status TEXT)''')
    conn.commit()
    conn.close()

@click.group()
def cli():
    """传统行业SaaS退出策略管理工具"""
    init_db()

@cli.command()
@click.option('--name', prompt='行业名称', help='目标行业')
@click.option('--tech', type=click.Choice(['无', '低', '中']), default='无', help='技术能力')
@click.option('--notes', default='', help='备注')
def add_industry(name, tech, notes):
    """添加目标传统行业"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO industries (name, tech_capability, notes) VALUES (?, ?, ?)",
                  (name, tech, notes))
        conn.commit()
        click.echo(f"✓ 已添加行业: {name} (技术能力: {tech})")
    except sqlite3.IntegrityError:
        click.echo(f"✗ 行业 {name} 已存在", err=True)
    finally:
        conn.close()

@cli.command()
def list_industries():
    """列出所有目标行业"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute("SELECT id, name, tech_capability, notes FROM industries").fetchall()
    conn.close()
    
    if not rows:
        click.echo("暂无行业数据")
        return
    
    for row in rows:
        click.echo(f"[{row[0]}] {row[1]} | 技术能力: {row[2]} | {row[3]}")

@cli.command()
@click.option('--company', prompt='公司名称', help='合作伙伴公司')
@click.option('--ceo', prompt='CEO姓名', help='CEO全名')
@click.option('--industry-id', prompt='行业ID', type=int, help='所属行业ID')
@click.option('--trust', default=1, type=click.IntRange(1, 10), help='信任等级(1-10)')
def add_partner(company, ceo, industry_id, trust):
    """添加设计合作伙伴（潜在收购方）"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    c.execute("""INSERT INTO partners (company, ceo_name, industry_id, relationship_start, 
                 last_contact, trust_level, notes) VALUES (?, ?, ?, ?, ?, ?, ?)""",
              (company, ceo, industry_id, today, today, trust, ''))
    conn.commit()
    partner_id = c.lastrowid
    conn.close()
    click.echo(f"✓ 已添加合作伙伴: {company} (CEO: {ceo}) [ID: {partner_id}]")

@cli.command()
@click.option('--industry-id', type=int, help='筛选行业')
def list_partners(industry_id):
    """列出所有合作伙伴"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    if industry_id:
        rows = c.execute("""SELECT p.id, p.company, p.ceo_name, i.name, p.trust_level, 
                            p.last_contact FROM partners p JOIN industries i ON p.industry_id=i.id
                            WHERE p.industry_id=?""", (industry_id,)).fetchall()
    else:
        rows = c.execute("""SELECT p.id, p.company, p.ceo_name, i.name, p.trust_level, 
                            p.last_contact FROM partners p JOIN industries i 
                            ON p.industry_id=i.id""").fetchall()
    conn.close()
    
    if not rows:
        click.echo("暂无合作伙伴")
        return
    
    for row in rows:
        click.echo(f"[{row[0]}] {row[1]} | CEO: {row[2]} | 行业: {row[3]} | 信任: {row[4]}/10 | 最后联系: {row[5]}")

@cli.command()
@click.option('--partner-id', prompt='合作伙伴ID', type=int)
@click.option('--type', prompt='互动类型', type=click.Choice(['会议', '电话', '邮件', '晚餐', '活动']))
@click.option('--summary', prompt='互动摘要', help='关键内容')
def log_interaction(partner_id, type, summary):
    """记录CEO级别互动"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    
    c.execute("SELECT company FROM partners WHERE id=?", (partner_id,))
    partner = c.fetchone()
    if not partner:
        click.echo(f"✗ 合作伙伴ID {partner_id} 不存在", err=True)
        conn.close()
        return
    
    c.execute("INSERT INTO interactions (partner_id, date, type, summary) VALUES (?, ?, ?, ?)",
              (partner_id, today, type, summary))
    c.execute("UPDATE partners SET last_contact=? WHERE id=?", (today, partner_id))
    conn.commit()
    conn.close()
    click.echo(f"✓ 已记录与 {partner[0]} 的互动 ({type})")

@cli.command()
@click.option('--partner-id', type=int, help='查看特定合作伙伴')
@click.option('--days', default=90, help='最近N天')
def show_interactions(partner_id, days):
    """查看互动历史"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    if partner_id:
        rows = c.execute("""SELECT i.date, p.company, i.type, i.summary FROM interactions i
                            JOIN partners p ON i.partner_id=p.id WHERE i.partner_id=?
                            ORDER BY i.date DESC LIMIT 50""", (partner_id,)).fetchall()
    else:
        rows = c.execute("""SELECT i.date, p.company, i.type, i.summary FROM interactions i
                            JOIN partners p ON i.partner_id=p.id
                            ORDER BY i.date DESC LIMIT 50""").fetchall()
    conn.close()
    
    if not rows:
        click.echo("暂无互动记录")
        return
    
    for row in rows:
        click.echo(f"{row[0]} | {row[1]} | {row[2]} | {row[3]}")

@cli.command()
@click.option('--partner-id', prompt='合作伙伴ID', type=int)
@click.option('--type', prompt='机会类型', type=click.Choice(['整体收购', '相邻收购', '战略合作']))
@click.option('--value', prompt='估值(万美元)', type=int)
@click.option('--notes', default='', help='详细说明')
def add_opportunity(partner_id, type, value, notes):
    """识别收购机会"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    
    c.execute("SELECT company FROM partners WHERE id=?", (partner_id,))
    partner = c.fetchone()
    if not partner:
        click.echo(f"✗ 合作伙伴ID {partner_id} 不存在", err=True)
        conn.close()
        return
    
    c.execute("""INSERT INTO opportunities (partner_id, type, status, value_estimate, notes, created_date)
                 VALUES (?, ?, ?, ?, ?, ?)""", (partner_id, type, '评估中', value, notes, today))
    conn.commit()
    opp_id = c.lastrowid
    conn.close()
    click.echo(f"✓ 已添加机会: {partner[0]} - {type} (估值: ${value}万) [ID: {opp_id}]")

@cli.command()
@click.option('--status', type=click.Choice(['评估中', '谈判中', '已完成', '已放弃']), help='筛选状态')
def list_opportunities(status):
    """列出所有收购机会"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    if status:
        rows = c.execute("""SELECT o.id, p.company, o.type, o.status, o.value_estimate, o.created_date
                            FROM opportunities o JOIN partners p ON o.partner_id=p.id
                            WHERE o.status=? ORDER BY o.created_date DESC""", (status,)).fetchall()
    else:
        rows = c.execute("""SELECT o.id, p.company, o.type, o.status, o.value_estimate, o.created_date
                            FROM opportunities o JOIN partners p ON o.partner_id=p.id
                            ORDER BY o.created_date DESC""").fetchall()
    conn.close()
    
    if not rows:
        click.echo("暂无收购机会")
        return
    
    for row in rows:
        click.echo(f"[{row[0]}] {row[1]} | {row[2]} | {row[3]} | ${row[4]}万 | {row[5]}")

@cli.command()
@click.option('--opp-id', prompt='机会ID', type=int)
@click.option('--status', prompt='新状态', type=click.Choice(['评估中', '谈判中', '已完成', '已放弃']))
def update_opportunity(opp_id, status):
    """更新机会状态"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE opportunities SET status=? WHERE id=?", (status, opp_id))
    conn.commit()
    conn.close()
    click.echo(f"✓ 机会 {opp_id} 状态已更新为: {status}")

@cli.command()
@click.option('--amount', prompt='金额(万美元)', type=int)
@click.option('--purpose', prompt='用途', help='资金用途说明')
def add_funding(amount, purpose):
    """记录融资（用于建立可信度）"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    c.execute("INSERT INTO funding (amount, date, purpose, status) VALUES (?, ?, ?, ?)",
              (amount, today, purpose, '已到账'))
    conn.commit()
    conn.close()
    click.echo(f"✓ 已记录融资: ${amount}万 - {purpose}")

@cli.command()
def dashboard():
    """显示退出策略仪表盘"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    industries = c.execute("SELECT COUNT(*) FROM industries").fetchone()[0]
    partners = c.execute("SELECT COUNT(*) FROM partners").fetchone()[0]
    opportunities = c.execute("SELECT COUNT(*) FROM opportunities WHERE status!='已放弃'").fetchone()[0]
    total_value = c.execute("SELECT SUM(value_estimate) FROM opportunities WHERE status!='已放弃'").fetchone()[0] or 0
    funding = c.execute("SELECT SUM(amount) FROM funding").fetchone()[0] or 0
    
    high_trust = c.execute("SELECT COUNT(*) FROM partners WHERE trust_level>=7").fetchone()[0]
    recent_interactions = c.execute("""SELECT COUNT(*) FROM interactions 
                                       WHERE date >= date('now', '-30 days')""").fetchone()[0]
    
    conn.close()
    
    click.echo("\n=== 退出策略仪表盘 ===")
    click.echo(f"目标行业: {industries}")
    click.echo(f"设计合作伙伴: {partners} (高信任度: {high_trust})")
    click.echo(f"活跃收购机会: {opportunities} (总估值: ${total_value}万)")
    click.echo(f"累计融资: ${funding}万")
    click.echo(f"近30天互动: {recent_interactions}次")
    click.echo("=" * 30 + "\n")

if __name__ == '__main__':
    cli()