#!/usr/bin/env python3
#!/usr/bin/env python3
import click
import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
import re

DB_PATH = Path.home() / ".saas_exit_tracker.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS industries
                 (id INTEGER PRIMARY KEY, name TEXT UNIQUE, tech_distance INTEGER, 
                  self_build_capability INTEGER, notes TEXT, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS partners
                 (id INTEGER PRIMARY KEY, name TEXT, industry_id INTEGER, 
                  contact_name TEXT, contact_email TEXT, company_size INTEGER,
                  funding_stage TEXT, relationship_start TEXT, trust_score INTEGER DEFAULT 0,
                  last_contact TEXT, notes TEXT, FOREIGN KEY(industry_id) REFERENCES industries(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS interactions
                 (id INTEGER PRIMARY KEY, partner_id INTEGER, interaction_date TEXT,
                  interaction_type TEXT, ceo_involved INTEGER, notes TEXT, trust_delta INTEGER,
                  FOREIGN KEY(partner_id) REFERENCES partners(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS opportunities
                 (id INTEGER PRIMARY KEY, partner_id INTEGER, opportunity_type TEXT,
                  description TEXT, identified_date TEXT, status TEXT,
                  FOREIGN KEY(partner_id) REFERENCES partners(id))''')
    conn.commit()
    conn.close()

@click.group()
def cli():
    """SaaS退出策略追踪工具 - 18个月内实现低8位数退出"""
    init_db()

@cli.command()
@click.option('--name', prompt='行业名称', help='目标行业')
@click.option('--tech-distance', prompt='技术距离(1-10)', type=int, help='离技术圈距离，10=最远')
@click.option('--self-build', prompt='自建能力(1-10)', type=int, help='客户自建能力，1=无能力')
@click.option('--notes', default='', help='备注')
def add_industry(name, tech_distance, self_build, notes):
    """添加目标行业"""
    if tech_distance < 7 or self_build > 3:
        click.echo(f"⚠️  警告: 该行业可能不符合退出策略（需要tech_distance>=7且self_build<=3）")
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO industries VALUES (NULL,?,?,?,?,?)",
                  (name, tech_distance, self_build, notes, datetime.now().isoformat()))
        conn.commit()
        click.echo(f"✓ 已添加行业: {name} (评分: {tech_distance}/10 技术距离, {self_build}/10 自建能力)")
    except sqlite3.IntegrityError:
        click.echo(f"✗ 行业已存在: {name}")
    finally:
        conn.close()

@cli.command()
def list_industries():
    """列出所有行业及评估"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute("SELECT id, name, tech_distance, self_build_capability, notes FROM industries ORDER BY tech_distance DESC").fetchall()
    conn.close()
    
    if not rows:
        click.echo("暂无行业数据")
        return
    
    click.echo("\n目标行业列表:")
    for row in rows:
        score = row[2] + (10 - row[3])
        status = "🎯 优质" if score >= 14 else "⚠️  一般"
        click.echo(f"{status} [{row[0]}] {row[1]} | 技术距离:{row[2]} 自建能力:{row[3]} | {row[4]}")

@cli.command()
@click.option('--name', prompt='公司名称')
@click.option('--industry-id', prompt='行业ID', type=int)
@click.option('--contact-name', prompt='联系人姓名')
@click.option('--contact-email', prompt='联系人邮箱')
@click.option('--size', prompt='公司规模(人数)', type=int, default=50)
@click.option('--funding', prompt='融资阶段', default='Seed')
def add_partner(name, industry_id, contact_name, contact_email, size, funding):
    """添加设计合作伙伴（潜在收购方）"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO partners VALUES (NULL,?,?,?,?,?,?,?,0,?,?)",
              (name, industry_id, contact_name, contact_email, size, funding,
               datetime.now().isoformat(), datetime.now().isoformat(), ''))
    conn.commit()
    conn.close()
    click.echo(f"✓ 已添加合作伙伴: {name} ({contact_name})")

@cli.command()
@click.option('--partner-id', prompt='合作伙伴ID', type=int)
@click.option('--type', prompt='互动类型', type=click.Choice(['email', 'call', 'meeting', 'demo', 'contract']))
@click.option('--ceo-involved', prompt='CEO参与?', type=bool, default=False)
@click.option('--notes', default='')
@click.option('--trust-delta', prompt='信任度变化(-5到+5)', type=int, default=1)
def log_interaction(partner_id, type, ceo_involved, notes, trust_delta):
    """记录互动（自动更新信任度）"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("SELECT trust_score FROM partners WHERE id=?", (partner_id,))
    result = c.fetchone()
    if not result:
        click.echo("✗ 合作伙伴不存在")
        conn.close()
        return
    
    new_trust = max(0, min(100, result[0] + trust_delta))
    
    c.execute("INSERT INTO interactions VALUES (NULL,?,?,?,?,?,?)",
              (partner_id, datetime.now().isoformat(), type, int(ceo_involved), notes, trust_delta))
    c.execute("UPDATE partners SET trust_score=?, last_contact=? WHERE id=?",
              (new_trust, datetime.now().isoformat(), partner_id))
    conn.commit()
    conn.close()
    
    click.echo(f"✓ 已记录互动 | 信任度: {result[0]} → {new_trust}")
    if new_trust >= 70:
        click.echo("🎯 信任度达到70+，可考虑探索收购意向")

@cli.command()
@click.option('--min-trust', default=50, help='最低信任度')
@click.option('--min-months', default=12, help='最短关系月数')
def list_partners(min_trust, min_months):
    """列出合作伙伴及退出准备度"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    cutoff_date = (datetime.now() - timedelta(days=min_months*30)).isoformat()
    
    rows = c.execute("""
        SELECT p.id, p.name, p.contact_name, p.trust_score, p.relationship_start, 
               p.last_contact, i.name, p.company_size, p.funding_stage,
               (SELECT COUNT(*) FROM interactions WHERE partner_id=p.id AND ceo_involved=1) as ceo_count
        FROM partners p
        JOIN industries i ON p.industry_id = i.id
        WHERE p.trust_score >= ? AND p.relationship_start <= ?
        ORDER BY p.trust_score DESC
    """, (min_trust, cutoff_date)).fetchall()
    conn.close()
    
    if not rows:
        click.echo(f"暂无符合条件的合作伙伴（信任度>={min_trust}，关系>={min_months}月）")
        return
    
    click.echo(f"\n🎯 退出候选合作伙伴 (信任度>={min_trust}, 关系>={min_months}月):\n")
    for row in rows:
        months = (datetime.now() - datetime.fromisoformat(row[4])).days // 30
        status = "🔥 高优先级" if row[3] >= 80 and months >= 18 else "✓ 可接触"
        click.echo(f"{status} [{row[0]}] {row[1]} ({row[6]})")
        click.echo(f"  联系人: {row[2]} | 信任度: {row[3]}/100 | 关系: {months}月")
        click.echo(f"  CEO互动: {row[9]}次 | 规模: {row[7]}人 | 融资: {row[8]}")
        click.echo(f"  最后联系: {row[5][:10]}\n")

@cli.command()
@click.option('--partner-id', prompt='合作伙伴ID', type=int)
@click.option('--type', prompt='机会类型', type=click.Choice(['feature_request', 'budget_increase', 'team_expansion', 'competitor_mention']))
@click.option('--description', prompt='描述')
def add_opportunity(partner_id, type, description):
    """识别相邻机会（收购信号）"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO opportunities VALUES (NULL,?,?,?,?,?)",
              (partner_id, type, description, datetime.now().isoformat(), 'active'))
    conn.commit()
    conn.close()
    
    signal_map = {
        'feature_request': '功能需求增加 → 可能考虑收购以快速获得能力',
        'budget_increase': '预算增加 → 财务状况改善，收购能力提升',
        'team_expansion': '团队扩张 → 业务增长，可能需要技术整合',
        'competitor_mention': '提及竞品 → 市场压力，可能寻求并购'
    }
    
    click.echo(f"✓ 已记录机会")
    click.echo(f"💡 信号解读: {signal_map[type]}")

@cli.command()
def exit_readiness():
    """退出准备度报告"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    total_partners = c.execute("SELECT COUNT(*) FROM partners").fetchone()[0]
    high_trust = c.execute("SELECT COUNT(*) FROM partners WHERE trust_score >= 70").fetchone()[0]
    mature_relationships = c.execute("""
        SELECT COUNT(*) FROM partners 
        WHERE julianday('now') - julianday(relationship_start) >= 365
    """).fetchone()[0]
    
    recent_opps = c.execute("""
        SELECT COUNT(*) FROM opportunities 
        WHERE julianday('now') - julianday(identified_date) <= 90 AND status='active'
    """).fetchone()[0]
    
    top_candidates = c.execute("""
        SELECT p.name, p.trust_score, 
               CAST((julianday('now') - julianday(p.relationship_start)) / 30 AS INTEGER) as months
        FROM partners p
        WHERE p.trust_score >= 70 
        AND julianday('now') - julianday(p.relationship_start) >= 365
        ORDER BY p.trust_score DESC LIMIT 3
    """).fetchall()
    
    conn.close()
    
    click.echo("\n📊 退出准备度报告\n")
    click.echo(f"合作伙伴总数: {total_partners}")
    click.echo(f"高信任度(70+): {high_trust} ({high_trust/max(total_partners,1)*100:.0f}%)")
    click.echo(f"成熟关系(12月+): {mature_relationships}")
    click.echo(f"近期机会(90天): {recent_opps}")
    
    readiness_score = (high_trust * 30 + mature_relationships * 40 + min(recent_opps, 5) * 6)
    
    click.echo(f"\n🎯 退出准备度: {readiness_score}/100")
    
    if readiness_score >= 80:
        click.echo("✓ 已具备退出条件，建议主动接触收购意向")
    elif readiness_score >= 50:
        click.echo("⚠️  接近退出窗口，继续深化关键合作伙伴关系")
    else:
        click.echo("📈 早期阶段，专注建立信任和识别机会")
    
    if top_candidates:
        click.echo("\n🔥 Top 3 退出候选:")
        for name, trust, months in top_candidates:
            click.echo(f"  • {name} | 信任度:{trust} | 关系:{months}月")

@cli.command()
@click.option('--partner-id', type=int, help='合作伙伴ID（留空显示全部）')
def timeline(partner_id):
    """查看互动时间线"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    if partner_id:
        rows = c.execute("""
            SELECT i.interaction_date, i.interaction_type, i.ceo_involved, 
                   i.notes, i.trust_delta, p.name
            FROM interactions i
            JOIN partners p ON i.partner_id = p.id
            WHERE i.partner_id = ?
            ORDER BY i.interaction_date DESC LIMIT 20
        """, (partner_id,)).fetchall()
    else:
        rows = c.execute("""
            SELECT i.interaction_date, i.interaction_type, i.ceo_involved, 
                   i.notes, i.trust_delta, p.name
            FROM interactions i
            JOIN partners p ON i.partner_id = p.id
            ORDER BY i.interaction_date DESC LIMIT 50
        """).fetchall()
    
    conn.close()
    
    if not rows:
        click.echo("暂无互动记录")
        return
    
    click.echo("\n📅 互动时间线:\n")
    for row in rows:
        ceo_badge = "👔" if row[2] else "  "
        delta_str = f"(+{row[4]})" if row[4] > 0 else f"({row[4]})" if row[4] < 0 else ""
        click.echo(f"{ceo_badge} {row[0][:10]} | {row[5]} | {row[1]} {delta_str}")
        if row[3]:
            click.echo(f"     {row[3]}")

if __name__ == '__main__':
    cli()