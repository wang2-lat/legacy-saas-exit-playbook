#!/usr/bin/env python3
#!/usr/bin/env python3
import click
import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
import os

DB_PATH = Path.home() / ".saas_exit_tracker.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS industries (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            legacy_score INTEGER DEFAULT 0,
            market_size TEXT,
            tech_adoption TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            company TEXT,
            role TEXT,
            industry_id INTEGER,
            relationship_level INTEGER DEFAULT 1,
            email TEXT,
            phone TEXT,
            last_contact DATE,
            next_followup DATE,
            notes TEXT,
            is_design_partner BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (industry_id) REFERENCES industries(id)
        );
        
        CREATE TABLE IF NOT EXISTS interactions (
            id INTEGER PRIMARY KEY,
            contact_id INTEGER NOT NULL,
            date DATE NOT NULL,
            type TEXT,
            summary TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (contact_id) REFERENCES contacts(id)
        );
        
        CREATE TABLE IF NOT EXISTS opportunities (
            id INTEGER PRIMARY KEY,
            company TEXT NOT NULL,
            industry_id INTEGER,
            stage TEXT DEFAULT 'identified',
            valuation_range TEXT,
            fit_score INTEGER DEFAULT 0,
            contact_id INTEGER,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (industry_id) REFERENCES industries(id),
            FOREIGN KEY (contact_id) REFERENCES contacts(id)
        );
        
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY,
            date DATE NOT NULL,
            funding_amount INTEGER DEFAULT 0,
            team_size INTEGER DEFAULT 0,
            partnerships_count INTEGER DEFAULT 0,
            mrr INTEGER DEFAULT 0,
            design_partners INTEGER DEFAULT 0
        );
    """)
    conn.commit()
    conn.close()

@click.group()
def cli():
    """SaaS Exit Playbook Tracker - 18个月卖出策略执行工具"""
    init_db()

@cli.group()
def industry():
    """行业筛选与评估"""
    pass

@industry.command()
@click.argument('name')
@click.option('--score', type=int, default=0, help='传统行业评分 (0-100)')
@click.option('--market-size', default='', help='市场规模')
@click.option('--tech-adoption', default='', help='技术采用程度')
@click.option('--notes', default='', help='备注')
def add(name, score, market_size, tech_adoption, notes):
    """添加目标行业"""
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO industries (name, legacy_score, market_size, tech_adoption, notes) VALUES (?, ?, ?, ?, ?)",
            (name, score, market_size, tech_adoption, notes)
        )
        conn.commit()
        click.echo(f"✓ 已添加行业: {name} (评分: {score})")
    except sqlite3.IntegrityError:
        click.echo(f"✗ 行业 {name} 已存在", err=True)
    finally:
        conn.close()

@industry.command()
def list():
    """列出所有行业"""
    conn = get_db()
    rows = conn.execute("SELECT * FROM industries ORDER BY legacy_score DESC").fetchall()
    conn.close()
    
    if not rows:
        click.echo("暂无行业数据")
        return
    
    for row in rows:
        click.echo(f"\n[{row['id']}] {row['name']} - 评分: {row['legacy_score']}")
        if row['market_size']:
            click.echo(f"  市场规模: {row['market_size']}")
        if row['tech_adoption']:
            click.echo(f"  技术采用: {row['tech_adoption']}")
        if row['notes']:
            click.echo(f"  备注: {row['notes']}")

@cli.group()
def contact():
    """潜在收购方关系管理"""
    pass

@contact.command()
@click.argument('name')
@click.option('--company', required=True, help='公司名称')
@click.option('--role', default='', help='职位')
@click.option('--industry-id', type=int, help='关联行业ID')
@click.option('--email', default='', help='邮箱')
@click.option('--phone', default='', help='电话')
@click.option('--design-partner', is_flag=True, help='标记为设计合作伙伴')
def add(name, company, role, industry_id, email, phone, design_partner):
    """添加联系人"""
    conn = get_db()
    conn.execute(
        "INSERT INTO contacts (name, company, role, industry_id, email, phone, is_design_partner) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, company, role, industry_id, email, phone, 1 if design_partner else 0)
    )
    conn.commit()
    conn.close()
    click.echo(f"✓ 已添加联系人: {name} @ {company}")

@contact.command()
@click.option('--design-partners', is_flag=True, help='仅显示设计合作伙伴')
def list(design_partners):
    """列出所有联系人"""
    conn = get_db()
    query = "SELECT c.*, i.name as industry_name FROM contacts c LEFT JOIN industries i ON c.industry_id = i.id"
    if design_partners:
        query += " WHERE c.is_design_partner = 1"
    query += " ORDER BY c.relationship_level DESC, c.last_contact DESC"
    
    rows = conn.execute(query).fetchall()
    conn.close()
    
    if not rows:
        click.echo("暂无联系人")
        return
    
    for row in rows:
        dp = " [设计合作伙伴]" if row['is_design_partner'] else ""
        click.echo(f"\n[{row['id']}] {row['name']} @ {row['company']}{dp}")
        if row['role']:
            click.echo(f"  职位: {row['role']}")
        if row['industry_name']:
            click.echo(f"  行业: {row['industry_name']}")
        click.echo(f"  关系等级: {row['relationship_level']}/5")
        if row['last_contact']:
            click.echo(f"  最后联系: {row['last_contact']}")
        if row['next_followup']:
            click.echo(f"  下次跟进: {row['next_followup']}")

@contact.command()
@click.argument('contact_id', type=int)
@click.option('--type', default='email', help='沟通类型 (email/call/meeting)')
@click.option('--summary', required=True, help='沟通摘要')
@click.option('--next-days', type=int, default=30, help='下次跟进天数')
def log(contact_id, type, summary, next_days):
    """记录沟通"""
    conn = get_db()
    today = datetime.now().date()
    next_date = today + timedelta(days=next_days)
    
    conn.execute(
        "INSERT INTO interactions (contact_id, date, type, summary) VALUES (?, ?, ?, ?)",
        (contact_id, today, type, summary)
    )
    conn.execute(
        "UPDATE contacts SET last_contact = ?, next_followup = ? WHERE id = ?",
        (today, next_date, contact_id)
    )
    conn.commit()
    conn.close()
    click.echo(f"✓ 已记录沟通，下次跟进: {next_date}")

@contact.command()
def reminders():
    """查看待跟进提醒"""
    conn = get_db()
    today = datetime.now().date()
    rows = conn.execute(
        "SELECT * FROM contacts WHERE next_followup <= ? ORDER BY next_followup",
        (today,)
    ).fetchall()
    conn.close()
    
    if not rows:
        click.echo("✓ 暂无待跟进联系人")
        return
    
    click.echo(f"需要跟进的联系人 ({len(rows)}):\n")
    for row in rows:
        click.echo(f"[{row['id']}] {row['name']} @ {row['company']}")
        click.echo(f"  应跟进日期: {row['next_followup']}")
        if row['notes']:
            click.echo(f"  备注: {row['notes']}")
        click.echo()

@cli.group()
def opportunity():
    """收购机会识别与管理"""
    pass

@opportunity.command()
@click.argument('company')
@click.option('--industry-id', type=int, help='行业ID')
@click.option('--stage', default='identified', help='阶段: identified/contacted/negotiating/due_diligence/closed')
@click.option('--valuation', default='', help='估值范围')
@click.option('--fit-score', type=int, default=0, help='匹配度评分 (0-100)')
@click.option('--contact-id', type=int, help='关联联系人ID')
@click.option('--notes', default='', help='备注')
def add(company, industry_id, stage, valuation, fit_score, contact_id, notes):
    """添加收购机会"""
    conn = get_db()
    conn.execute(
        "INSERT INTO opportunities (company, industry_id, stage, valuation_range, fit_score, contact_id, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (company, industry_id, stage, valuation, fit_score, contact_id, notes)
    )
    conn.commit()
    conn.close()
    click.echo(f"✓ 已添加收购机会: {company}")

@opportunity.command()
def pipeline():
    """查看交易管道"""
    conn = get_db()
    rows = conn.execute("""
        SELECT o.*, i.name as industry_name, c.name as contact_name
        FROM opportunities o
        LEFT JOIN industries i ON o.industry_id = i.id
        LEFT JOIN contacts c ON o.contact_id = c.id
        ORDER BY o.fit_score DESC, o.created_at DESC
    """).fetchall()
    conn.close()
    
    if not rows:
        click.echo("暂无收购机会")
        return
    
    stages = {}
    for row in rows:
        stage = row['stage']
        if stage not in stages:
            stages[stage] = []
        stages[stage].append(row)
    
    for stage, opps in stages.items():
        click.echo(f"\n=== {stage.upper()} ({len(opps)}) ===")
        for opp in opps:
            click.echo(f"\n[{opp['id']}] {opp['company']} - 匹配度: {opp['fit_score']}")
            if opp['industry_name']:
                click.echo(f"  行业: {opp['industry_name']}")
            if opp['valuation_range']:
                click.echo(f"  估值: {opp['valuation_range']}")
            if opp['contact_name']:
                click.echo(f"  联系人: {opp['contact_name']}")
            if opp['notes']:
                click.echo(f"  备注: {opp['notes']}")

@opportunity.command()
@click.argument('opp_id', type=int)
@click.argument('stage')
def update_stage(opp_id, stage):
    """更新交易阶段"""
    conn = get_db()
    conn.execute("UPDATE opportunities SET stage = ? WHERE id = ?", (stage, opp_id))
    conn.commit()
    conn.close()
    click.echo(f"✓ 已更新阶段为: {stage}")

@cli.group()
def metrics():
    """关键指标管理"""
    pass

@metrics.command()
@click.option('--funding', type=int, default=0, help='融资金额')
@click.option('--team-size', type=int, default=0, help='团队规模')
@click.option('--partnerships', type=int, default=0, help='合作伙伴数量')
@click.option('--mrr', type=int, default=0, help='月度经常性收入')
@click.option('--design-partners', type=int, default=0, help='设计合作伙伴数量')
def update(funding, team_size, partnerships, mrr, design_partners):
    """更新当前指标"""
    conn = get_db()
    today = datetime.now().date()
    conn.execute(
        "INSERT INTO metrics (date, funding_amount, team_size, partnerships_count, mrr, design_partners) VALUES (?, ?, ?, ?, ?, ?)",
        (today, funding, team_size, partnerships, mrr, design_partners)
    )
    conn.commit()
    conn.close()
    click.echo("✓ 已更新指标")

@metrics.command()
def dashboard():
    """显示仪表板"""
    conn = get_db()
    
    latest = conn.execute("SELECT * FROM metrics ORDER BY date DESC LIMIT 1").fetchone()
    industry_count = conn.execute("SELECT COUNT(*) as cnt FROM industries").fetchone()['cnt']
    contact_count = conn.execute("SELECT COUNT(*) as cnt FROM contacts").fetchone()['cnt']
    dp_count = conn.execute("SELECT COUNT(*) as cnt FROM contacts WHERE is_design_partner = 1").fetchone()['cnt']
    opp_count = conn.execute("SELECT COUNT(*) as cnt FROM opportunities").fetchone()['cnt']
    active_deals = conn.execute("SELECT COUNT(*) as cnt FROM opportunities WHERE stage IN ('contacted', 'negotiating', 'due_diligence')").fetchone()['cnt']
    
    conn.close()
    
    click.echo("\n=== SaaS Exit Playbook 仪表板 ===\n")
    
    click.echo("【合法性指标】")
    if latest:
        click.echo(f"  融资金额: ${latest['funding_amount']:,}")
        click.echo(f"  团队规模: {latest['team_size']} 人")
        click.echo(f"  合作伙伴: {latest['partnerships_count']}")
        click.echo(f"  MRR: ${latest['mrr']:,}")
        click.echo(f"  设计合作伙伴: {latest['design_partners']}")
    else:
        click.echo("  (暂无数据，使用 'metrics update' 更新)")
    
    click.echo("\n【执行进度】")
    click.echo(f"  目标行业: {industry_count}")
    click.echo(f"  关系网络: {contact_count} 联系人 ({dp_count} 设计合作伙伴)")
    click.echo(f"  收购机会: {opp_count} ({active_deals} 活跃交易)")
    
    click.echo()

if __name__ == '__main__':
    cli()