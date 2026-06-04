#!/usr/bin/env python3
"""
交易审计 MySQL 存储层
- 建表(幂等): trade_audit + trade_audit_signal + audit_log
- CRUD: 插入审计记录、信号、查询历史统计
- 数据校验: validate_audit_record()

依赖: pymysql, pyyaml
"""

import os
import sys
from contextlib import contextmanager
from datetime import date, datetime
from typing import Optional

import pymysql
import yaml

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "review_config.yaml")


# ============================================================
# 配置 & 连接
# ============================================================

def _load_mysql_config() -> dict:
    """从 review_config.yaml 读取 MySQL 配置，环境变量覆盖密码"""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    else:
        cfg = {}

    mysql_cfg = cfg.get("mysql", {})
    env_pwd = os.environ.get("MYSQL_PWD", "")
    return {
        "host": mysql_cfg.get("host", "192.168.123.104"),
        "port": mysql_cfg.get("port", 3306),
        "user": mysql_cfg.get("user", "root"),
        "password": env_pwd or mysql_cfg.get("password", ""),
        "database": mysql_cfg.get("database", "hermes"),
        "charset": "utf8mb4",
    }


@contextmanager
def get_conn(config: dict = None):
    """
    pymysql 上下文管理器
    用法:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(...)
            conn.commit()
    """
    cfg = config or _load_mysql_config()
    conn = pymysql.connect(**cfg)
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ============================================================
# 建表 SQL
# ============================================================

CREATE_TRADE_AUDIT = """
CREATE TABLE IF NOT EXISTS trade_audit (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    -- A: 基础信息
    account         VARCHAR(30)  NOT NULL,
    stock_code      VARCHAR(10)  NOT NULL,
    stock_name      VARCHAR(30)  NOT NULL,
    industry        VARCHAR(30),
    buy_date        DATE         NOT NULL,
    buy_price       DECIMAL(10,3) NOT NULL,
    buy_shares      INT          NOT NULL,
    buy_amount      DECIMAL(12,2) NOT NULL,
    sell_date       DATE         NOT NULL,
    sell_price      DECIMAL(10,3) NOT NULL,
    sell_shares     INT          NOT NULL,
    sell_amount     DECIMAL(12,2) NOT NULL,
    hold_days       INT          NOT NULL,
    realized_pnl    DECIMAL(12,2) NOT NULL,
    pnl_rate        DECIMAL(8,4) NOT NULL,
    total_fees      DECIMAL(10,2),
    -- B: 入场环境
    mkt_state       VARCHAR(20)  COMMENT 'strong/oscillating/weak/extreme',
    mkt_index_close DECIMAL(10,2),
    mkt_index_chg   DECIMAL(6,2),
    mkt_trend       VARCHAR(20)  COMMENT 'bull/bear/sideways',
    mkt_above_ma20  TINYINT,
    stk_trend       VARCHAR(20),
    stk_ma_arrange  VARCHAR(20)  COMMENT 'bullish/bearish/intertwined',
    stk_ma_support  VARCHAR(30)  COMMENT 'on_ma20/on_ma60/above/below/on_resistance',
    stk_ma_dist_pct DECIMAL(6,2),
    stk_boll_zone   VARCHAR(20)  COMMENT 'above_upper/upper_zone/mid_zone/lower_zone/below_lower',
    stk_boll_pctb   DECIMAL(8,4),
    stk_boll_width  VARCHAR(20)  COMMENT 'expanding/contracting/flat',
    stk_vol_ratio   DECIMAL(6,2),
    stk_macd_state  VARCHAR(30),
    stk_rsi6        DECIMAL(6,2),
    stk_atr14       DECIMAL(10,3),
    stk_atr_pctb    DECIMAL(6,2) COMMENT 'ATR历史分位%',
    stk_atr_stop    DECIMAL(10,3) COMMENT 'ATR推导止损价',
    -- C: 操作定性
    trade_direction VARCHAR(30)  COMMENT '顺势买入/轻逆势买入/强逆势买入',
    entry_mode      VARCHAR(30)  COMMENT 'breakout/pullback/left_batch',
    entry_signal    VARCHAR(50)  COMMENT 'breakout/pullback/reversal/golden_cross/volume/...',
    entry_quality   VARCHAR(20)  COMMENT 'excellent/good/poor',
    hold_period     VARCHAR(20),
    is_profit       TINYINT,
    trade_category  VARCHAR(30)  COMMENT 'rule_profit/rule_loss/outside_profit/outside_loss',
    -- D: 仓位与风控
    position_ratio  DECIMAL(6,2),
    position_rule   VARCHAR(20)  COMMENT 'pass/exceed/critical',
    single_stock_limit TINYINT,
    stop_loss_set   TINYINT,
    stop_loss_type  VARCHAR(30),
    stop_loss_price DECIMAL(10,3),
    stop_loss_hit   TINYINT,
    max_drawdown_pct DECIMAL(8,4),
    risk_reward_planned DECIMAL(6,2),
    is_pyramid      TINYINT,
    -- E: 卖出审计
    sell_reason     VARCHAR(50),
    sell_trigger    VARCHAR(30)  COMMENT 'rule_triggered/subjective/emotional',
    sell_trend      VARCHAR(20),
    sell_boll_pctb  DECIMAL(6,4),
    sell_timing     VARCHAR(20)  COMMENT 'high/mid/low',
    max_price_hold  DECIMAL(10,3),
    min_price_hold  DECIMAL(10,3),
    max_profit_pct  DECIMAL(8,4),
    profit_unrealized_rate DECIMAL(8,4),
    sell_vs_plan    VARCHAR(20)  COMMENT 'per_plan/deviated',
    -- F: 事后验证
    post5_close     DECIMAL(10,3),
    post5_chg       DECIMAL(8,4),
    post5_high      DECIMAL(10,3),
    post5_low       DECIMAL(10,3),
    post10_close    DECIMAL(10,3),
    post10_chg      DECIMAL(8,4),
    post20_close    DECIMAL(10,3),
    post20_chg      DECIMAL(8,4),
    post20_high     DECIMAL(10,3),
    post20_low      DECIMAL(10,3),
    post60_chg      DECIMAL(8,4),
    post_new_high   TINYINT      COMMENT '卖出后20日内最高价>持仓期间最高价',
    sell_verdict    VARCHAR(20)  COMMENT 'correct/missed/early/normal',
    -- G: 情绪与纪律
    consecutive_losses INT,
    trades_same_day    INT,
    repeat_trades      INT,
    repeat_loss_count  INT,
    is_impulsive       TINYINT,
    impulsive_type     VARCHAR(50),
    in_blacklist       TINYINT,
    -- H: 综合评分
    strategy_tag       VARCHAR(50)  COMMENT '使用策略：低吸/突破/反转/龙头/补涨等',
    rule_violation     VARCHAR(500) COMMENT '具体违反了哪些规则（多条逗号分隔）',
    entry_score        TINYINT,
    exit_score         TINYINT,
    discipline_score   TINYINT,
    risk_control_score TINYINT,
    total_score        TINYINT,
    mistake_category   VARCHAR(100),
    feedback_action    VARCHAR(50)  COMMENT 'none/observe/plan_ready/exclude/blacklist/improve_template',
    -- 元数据
    data_complete   TINYINT DEFAULT 1,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_trade (account, stock_code, buy_date, sell_date, sell_shares),
    INDEX idx_sell_date (sell_date),
    INDEX idx_stock (stock_code),
    INDEX idx_score (total_score),
    INDEX idx_category (trade_category),
    INDEX idx_direction (trade_direction),
    INDEX idx_impulsive (is_impulsive),
    INDEX idx_blacklist (in_blacklist)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

CREATE_TRADE_AUDIT_SIGNAL = """
CREATE TABLE IF NOT EXISTS trade_audit_signal (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    audit_id    INT NOT NULL,
    signal_name VARCHAR(30) NOT NULL COMMENT '突破/回调/反转/金叉/放量/缩量止跌/其他',
    FOREIGN KEY (audit_id) REFERENCES trade_audit(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

CREATE_AUDIT_LOG = """
CREATE TABLE IF NOT EXISTS audit_log (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    run_time         DATETIME NOT NULL,
    mode             VARCHAR(20) COMMENT 'batch/incremental/single/update_post',
    total_processed  INT DEFAULT 0,
    total_inserted   INT DEFAULT 0,
    total_skipped    INT DEFAULT 0,
    errors           TEXT,
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def create_tables(conn=None):
    """建表(幂等)，传 conn 则复用，否则自动创建"""
    auto_close = conn is None
    if auto_close:
        conn = pymysql.connect(**_load_mysql_config())

    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_TRADE_AUDIT)
            cur.execute(CREATE_TRADE_AUDIT_SIGNAL)
            cur.execute(CREATE_AUDIT_LOG)
        conn.commit()
    finally:
        if auto_close:
            conn.close()


# ============================================================
# 数据校验
# ============================================================

REQUIRED_FIELDS = [
    "account", "stock_code", "stock_name",
    "buy_date", "buy_price", "buy_shares", "buy_amount",
    "sell_date", "sell_price", "sell_shares", "sell_amount",
    "hold_days", "realized_pnl", "pnl_rate",
]


def _parse_date_value(value, field: str) -> date:
    """解析审计日期字段，失败时抛 ValueError。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError(f"{field} 日期格式应为 YYYY-MM-DD: {value}") from exc
    raise ValueError(f"{field} 不能为空")


def _require_positive_number(record: dict, field: str):
    value = record.get(field)
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须是数字") from exc
    if numeric <= 0:
        raise ValueError(f"{field} 必须大于0")


def validate_audit_record(record: dict) -> bool:
    """写入前校验必填字段，缺失或核心交易字段无效则抛 ValueError。"""
    missing = []
    for field in REQUIRED_FIELDS:
        value = record.get(field)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            missing.append(field)
    if missing:
        raise ValueError(f"审计记录缺少必填字段: {', '.join(missing)}")

    buy_date = _parse_date_value(record.get("buy_date"), "buy_date")
    sell_date = _parse_date_value(record.get("sell_date"), "sell_date")
    if sell_date < buy_date:
        raise ValueError("sell_date 不能早于 buy_date")

    for field in (
        "buy_price", "sell_price", "buy_shares", "sell_shares",
        "buy_amount", "sell_amount",
    ):
        _require_positive_number(record, field)

    return True


# ============================================================
# 字段映射: Python dict → MySQL 列名
# ============================================================

# trade_audit 全部列名(A-H + 元数据，不含id/created_at)
AUDIT_COLUMNS = [
    # A: 基础
    "account", "stock_code", "stock_name", "industry",
    "buy_date", "buy_price", "buy_shares", "buy_amount",
    "sell_date", "sell_price", "sell_shares", "sell_amount",
    "hold_days", "realized_pnl", "pnl_rate", "total_fees",
    # B: 入场环境
    "mkt_state", "mkt_index_close", "mkt_index_chg", "mkt_trend", "mkt_above_ma20",
    "stk_trend", "stk_ma_arrange", "stk_ma_support", "stk_ma_dist_pct",
    "stk_boll_zone", "stk_boll_pctb", "stk_boll_width",
    "stk_vol_ratio", "stk_macd_state", "stk_rsi6",
    "stk_atr14", "stk_atr_pctb", "stk_atr_stop",
    # C: 操作定性
    "trade_direction", "entry_mode", "entry_signal", "entry_quality",
    "hold_period", "is_profit", "trade_category",
    # D: 仓位与风控
    "position_ratio", "position_rule", "single_stock_limit",
    "stop_loss_set", "stop_loss_type", "stop_loss_price", "stop_loss_hit",
    "max_drawdown_pct", "risk_reward_planned", "is_pyramid",
    # E: 卖出审计
    "sell_reason", "sell_trigger", "sell_trend", "sell_boll_pctb", "sell_timing",
    "max_price_hold", "min_price_hold", "max_profit_pct", "profit_unrealized_rate",
    "sell_vs_plan",
    # F: 事后验证
    "post5_close", "post5_chg", "post5_high", "post5_low",
    "post10_close", "post10_chg",
    "post20_close", "post20_chg", "post20_high", "post20_low",
    "post60_chg", "post_new_high", "sell_verdict",
    # G: 情绪与纪律
    "consecutive_losses", "trades_same_day", "repeat_trades", "repeat_loss_count",
    "is_impulsive", "impulsive_type", "in_blacklist",
    # H: 综合评分
    "strategy_tag", "rule_violation",
    "entry_score", "exit_score", "discipline_score", "risk_control_score",
    "total_score", "mistake_category", "feedback_action",
    # 元数据
    "data_complete",
]

# 建INSERT语句的列名和占位符
_INSERT_COLS = ", ".join(AUDIT_COLUMNS)
_INSERT_PLACEHOLDERS = ", ".join(["%s"] * len(AUDIT_COLUMNS))


# ============================================================
# 插入审计记录
# ============================================================

def insert_audit(conn, record: dict) -> int:
    """
    插入一条审计记录，返回 audit_id。
    record 的 key 必须是 AUDIT_COLUMNS 中的列名。
    多余的 key 会被忽略，缺失的非必填字段写 NULL。
    用 uk_trade 唯一键做 INSERT ... ON DUPLICATE KEY UPDATE 实现去重。
    """
    validate_audit_record(record)

    # 按 AUDIT_COLUMNS 顺序取值，缺失则 None
    values = [record.get(col) for col in AUDIT_COLUMNS]

    # ON DUPLICATE KEY UPDATE: 冲突时更新所有非基础字段
    update_cols = [
        col for col in AUDIT_COLUMNS
        if col not in ("account", "stock_code", "buy_date", "sell_date", "sell_shares")
    ]
    update_clause = ", ".join(f"{col}=VALUES({col})" for col in update_cols)

    sql = (
        f"INSERT INTO trade_audit ({_INSERT_COLS}) "
        f"VALUES ({_INSERT_PLACEHOLDERS}) "
        f"ON DUPLICATE KEY UPDATE {update_clause}"
    )

    with conn.cursor() as cur:
        cur.execute(sql, values)
        audit_id = cur.lastrowid
        # ON DUPLICATE KEY UPDATE 时 lastrowid 返回已有行的 id
        if audit_id == 0:
            # 查询已存在记录的 id
            cur.execute(
                "SELECT id FROM trade_audit "
                "WHERE account=%s AND stock_code=%s AND buy_date=%s "
                "AND sell_date=%s AND sell_shares=%s",
                (record["account"], record["stock_code"], record["buy_date"],
                 record["sell_date"], record["sell_shares"]),
            )
            row = cur.fetchone()
            audit_id = row[0] if row else 0

    conn.commit()
    return audit_id


# ============================================================
# 插入信号
# ============================================================

def insert_signals(conn, audit_id: int, signals: list) -> int:
    """批量插入信号，返回插入条数"""
    if not signals or not audit_id:
        return 0

    sql = "INSERT INTO trade_audit_signal (audit_id, signal_name) VALUES (%s, %s)"
    rows = [(audit_id, s) for s in signals if s]

    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()
    return len(rows)


# ============================================================
# 查询历史统计（供黑名单判定）
# ============================================================

def query_stock_history_stats(stock_code: str, conn, account: str = None) -> dict:
    """
    查询某股在 trade_audit 中的历史统计：
    - total_loss_pct: 该股累计亏损比例(仅亏损笔)
    - loss_count: 亏损次数
    - outside_loss_count: 规则外亏损次数
    - total_trades: 总交易次数
    """
    base_where = "stock_code = %s"
    params = [stock_code]
    if account:
        base_where += " AND account = %s"
        params.append(account)

    with conn.cursor() as cur:
        # 总交易次数
        cur.execute(f"SELECT COUNT(*) FROM trade_audit WHERE {base_where}", params)
        total_trades = cur.fetchone()[0]

        # 亏损次数
        cur.execute(
            f"SELECT COUNT(*) FROM trade_audit WHERE {base_where} AND is_profit = 0",
            params,
        )
        loss_count = cur.fetchone()[0]

        # 规则外亏损次数
        cur.execute(
            f"SELECT COUNT(*) FROM trade_audit WHERE {base_where} "
            f"AND is_profit = 0 AND trade_category = '规则外亏损'",
            params,
        )
        outside_loss_count = cur.fetchone()[0]

        # 累计亏损比例(亏损笔的 pnl_rate 之和)
        cur.execute(
            f"SELECT COALESCE(SUM(pnl_rate), 0) FROM trade_audit "
            f"WHERE {base_where} AND is_profit = 0",
            params,
        )
        total_loss_pct = float(cur.fetchone()[0])

    return {
        "total_trades": total_trades,
        "loss_count": loss_count,
        "outside_loss_count": outside_loss_count,
        "total_loss_pct": total_loss_pct,
    }


# ============================================================
# 查询情绪指标（供冲动判定）
# ============================================================

def query_emotion_stats(account: str, buy_date, stock_code: str, conn) -> dict:
    """
    查询情绪相关统计：
    - consecutive_losses: 截止buy_date的连续亏损笔数
    - trades_same_day: 同日同账户交易笔数(含本笔)
    - repeat_trades: 同股历史交易次数(含本笔)
    - repeat_loss_count: 同股历史亏损次数
    """
    with conn.cursor() as cur:
        # 连续亏损笔数(从最近一笔往前数，遇到盈利即停)
        cur.execute(
            "SELECT is_profit FROM trade_audit "
            "WHERE account = %s AND sell_date < %s "
            "ORDER BY sell_date DESC, id DESC LIMIT 20",
            (account, buy_date),
        )
        rows = cur.fetchall()
        consecutive_losses = 0
        for row in rows:
            if row[0] == 0:
                consecutive_losses += 1
            else:
                break

        # 同日交易笔数(含本笔)
        cur.execute(
            "SELECT COUNT(*) FROM trade_audit "
            "WHERE account = %s AND buy_date = %s",
            (account, buy_date),
        )
        trades_same_day = cur.fetchone()[0] + 1  # +1 含本笔

        # 同股历史交易次数
        cur.execute(
            "SELECT COUNT(*) FROM trade_audit "
            "WHERE account = %s AND stock_code = %s",
            (account, stock_code),
        )
        repeat_trades = cur.fetchone()[0] + 1

        # 同股历史亏损次数
        cur.execute(
            "SELECT COUNT(*) FROM trade_audit "
            "WHERE account = %s AND stock_code = %s AND is_profit = 0",
            (account, stock_code),
        )
        repeat_loss_count = cur.fetchone()[0]

    return {
        "consecutive_losses": consecutive_losses,
        "trades_same_day": trades_same_day,
        "repeat_trades": repeat_trades,
        "repeat_loss_count": repeat_loss_count,
    }


# ============================================================
# 记录是否存在（增量模式用）
# ============================================================

def trade_exists(conn, account: str, stock_code: str,
                 buy_date, sell_date, sell_shares: int) -> bool:
    """查询审计记录是否已存在(按唯一键)"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM trade_audit "
            "WHERE account=%s AND stock_code=%s AND buy_date=%s "
            "AND sell_date=%s AND sell_shares=%s LIMIT 1",
            (account, stock_code, buy_date, sell_date, sell_shares),
        )
        return cur.fetchone() is not None


# ============================================================
# 审计日志
# ============================================================

def insert_audit_log(conn, mode: str, total_processed: int,
                     total_inserted: int, total_skipped: int = 0,
                     errors: str = ""):
    """写入审计运行日志"""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO audit_log (run_time, mode, total_processed, "
            "total_inserted, total_skipped, errors) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (datetime.now(), mode, total_processed, total_inserted,
             total_skipped, errors),
        )
    conn.commit()


# ============================================================
# 更新事后验证字段
# ============================================================

POST_UPDATE_COLUMNS = [
    "post5_close", "post5_chg", "post5_high", "post5_low",
    "post10_close", "post10_chg",
    "post20_close", "post20_chg", "post20_high", "post20_low",
    "post60_chg", "post_new_high", "sell_verdict",
    "max_price_hold",
    "exit_score", "total_score", "feedback_action",
]


def update_post_validation(conn, audit_id: int, post_data: dict) -> bool:
    """
    更新事后验证字段（T+5/10/20/60 cron 补充时使用）
    post_data: 只需包含需要更新的字段
    """
    if not audit_id or not post_data:
        return False

    sets = []
    values = []
    for col in POST_UPDATE_COLUMNS:
        if col in post_data and post_data[col] is not None:
            sets.append(f"{col} = %s")
            values.append(post_data[col])

    if not sets:
        return False

    values.append(audit_id)
    sql = f"UPDATE trade_audit SET {', '.join(sets)} WHERE id = %s"

    with conn.cursor() as cur:
        cur.execute(sql, values)
    conn.commit()
    return True


# ============================================================
# CLI: 建表 + 验证
# ============================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="交易审计 MySQL 存储层")
    parser.add_argument("command", choices=["create", "check", "stats"],
                        help="create=建表, check=连接测试, stats=表统计")
    parser.add_argument("--stock", default=None, help="统计指定股票(仅stats模式)")
    args = parser.parse_args()

    if args.command == "create":
        with get_conn() as conn:
            create_tables(conn)
        print("✅ 建表完成: trade_audit, trade_audit_signal, audit_log")

    elif args.command == "check":
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM trade_audit")
                cnt = cur.fetchone()[0]
                cur.execute("SHOW TABLES LIKE 'trade_audit%'")
                tables = [row[0] for row in cur.fetchall()]
                cur.execute("SHOW TABLES LIKE 'audit_log'")
                has_log = cur.fetchone() is not None
        print(f"✅ 连接成功")
        print(f"   trade_audit 记录数: {cnt}")
        print(f"   已有表: {tables}")
        print(f"   audit_log: {'存在' if has_log else '不存在'}")

    elif args.command == "stats":
        with get_conn() as conn:
            if args.stock:
                stats = query_stock_history_stats(args.stock, conn)
                print(f"股票 {args.stock} 历史统计:")
                print(f"  总交易: {stats['total_trades']}笔")
                print(f"  亏损: {stats['loss_count']}笔")
                print(f"  规则外亏损: {stats['outside_loss_count']}笔")
                print(f"  累计亏损率: {stats['total_loss_pct']:.2%}")
            else:
                with conn.cursor() as cur:
                    # 四分法统计
                    cur.execute(
                        "SELECT trade_category, COUNT(*) as cnt, "
                        "AVG(pnl_rate) as avg_pnl, SUM(realized_pnl) as total_pnl "
                        "FROM trade_audit GROUP BY trade_category"
                    )
                    rows = cur.fetchall()
                    if rows:
                        print("四分法统计:")
                        for row in rows:
                            print(f"  {row[0]}: {row[1]}笔, 均盈亏{row[2]:.2f}%, 总{row[3]}")
                    else:
                        print("暂无审计数据")


if __name__ == "__main__":
    main()
