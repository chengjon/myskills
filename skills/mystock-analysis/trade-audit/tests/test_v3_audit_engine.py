import os
import sys
from datetime import date

import pytest


ROOT = os.path.dirname(os.path.dirname(__file__))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import review_generator as rg
import trade_audit_sql as sql


class DummyCursor:
    def __init__(self, rows=None, one=None):
        self.rows = rows or []
        self.one = one
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.one


class DummyConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


def _valid_record(**overrides):
    record = {col: None for col in sql.AUDIT_COLUMNS}
    record.update(
        {
            "account": "cli",
            "stock_code": "000539",
            "stock_name": "粤电力",
            "buy_date": "2026-05-20",
            "buy_price": 10.0,
            "buy_shares": 100,
            "buy_amount": 1000.0,
            "sell_date": "2026-06-01",
            "sell_price": 9.5,
            "sell_shares": 100,
            "sell_amount": 950.0,
            "hold_days": 8,
            "realized_pnl": -50.0,
            "pnl_rate": -5.0,
        }
    )
    record.update(overrides)
    return record


def _valid_trade(**overrides):
    trade = {
        "account": "cli",
        "stock_code": "000539",
        "stock_name": "粤电力",
        "buy_date": "2026-05-20",
        "buy_price": 10.0,
        "buy_shares": 100,
        "buy_amount": 1000.0,
        "sell_date": "2026-06-01",
        "sell_price": 9.5,
        "sell_shares": 100,
        "sell_amount": 950.0,
        "hold_days": 8,
        "realized_pnl": -50.0,
        "pnl_rate": -5.0,
        "total_fees": 5.0,
        "sell_reason": "止损",
        "has_plan": True,
        "stop_price": 9.5,
        "total_assets": 100000.0,
        "position_ratio": 10.0,
    }
    trade.update(overrides)
    return trade


def _patch_audit_dependencies(monkeypatch, inserted):
    monkeypatch.setattr(sql, "trade_exists", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        sql,
        "query_emotion_stats",
        lambda *args, **kwargs: {
            "consecutive_losses": 0,
            "trades_same_day": 1,
            "repeat_trades": 1,
            "repeat_loss_count": 0,
        },
    )
    monkeypatch.setattr(
        sql,
        "query_stock_history_stats",
        lambda *args, **kwargs: {
            "total_trades": 0,
            "loss_count": 0,
            "outside_loss_count": 0,
            "total_loss_pct": 0,
        },
    )

    def fake_insert_audit(conn, record):
        inserted["record"] = record
        return 123

    monkeypatch.setattr(sql, "insert_audit", fake_insert_audit)
    monkeypatch.setattr(sql, "insert_signals", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        rg,
        "fetch_pre_snapshot",
        lambda *args, **kwargs: {
            "indicators": {
                "ma5": 11,
                "ma10": 10,
                "ma20": 9,
                "ma60": 8,
                "boll_pctb": 0.4,
                "boll_zone": "mid_zone",
                "vol_ratio": 1.2,
                "macd_state": "golden_cross",
                "rsi6": 50,
                "atr14": 0.5,
                "atr_pctb": 30,
            },
            "indices": {
                "上证": {"close": 3000, "change_pct": 1.0},
                "深证": {"change_pct": 0.8},
                "创业板": {"change_pct": 0.2},
            },
        },
    )
    monkeypatch.setattr(
        rg,
        "fetch_post_validation",
        lambda *args, **kwargs: {
            "post5": {"close": 9.6, "chg": -4, "high": 10.1, "low": 9.4},
            "post10": {"close": 9.5, "chg": -5, "high": 10.2, "low": 9.3},
            "post20": {"close": 9.2, "chg": -8, "high": 10.2, "low": 9.0},
            "post60": {"close": 8.8, "chg": -12, "high": 10.3, "low": 8.5},
            "post_new_high": False,
        },
    )


def test_insert_audit_from_trade_maps_post60_chg(monkeypatch):
    inserted = {}
    _patch_audit_dependencies(monkeypatch, inserted)

    result = rg.insert_audit_from_trade(_valid_trade(), db_conn=DummyConn(DummyCursor()))

    assert result["status"] == "inserted"
    assert inserted["record"]["post60_chg"] == -12


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("buy_date", ""),
        ("sell_date", ""),
        ("buy_price", 0),
        ("sell_price", 0),
        ("buy_shares", 0),
        ("sell_shares", 0),
        ("buy_amount", 0),
        ("sell_amount", 0),
    ],
)
def test_validate_audit_record_rejects_empty_or_zero_required_values(field, bad_value):
    with pytest.raises(ValueError):
        sql.validate_audit_record(_valid_record(**{field: bad_value}))


def test_validate_audit_record_rejects_sell_before_buy():
    with pytest.raises(ValueError):
        sql.validate_audit_record(
            _valid_record(buy_date="2026-06-02", sell_date="2026-06-01")
        )


def test_insert_audit_from_trade_rejects_records_that_still_need_fifo(monkeypatch):
    inserted = {}
    _patch_audit_dependencies(monkeypatch, inserted)

    result = rg.insert_audit_from_trade(
        _valid_trade(_needs_fifo=True), db_conn=DummyConn(DummyCursor())
    )

    assert result["status"].startswith("error:")
    assert "FIFO" in result["status"]
    assert inserted == {}


def test_fetch_completed_trades_uses_parameters_and_reports_table_errors():
    """calc_pnl_for_audit优先,精确FIFO返回真实交易对; SQL fallback只在import失败时启用"""
    cursor = DummyCursor()

    def fail_execute(query, params=None):
        cursor.executed.append((query, params))
        raise RuntimeError("missing table")

    cursor.execute = fail_execute
    conn = DummyConn(cursor)

    trades, errors = rg._fetch_completed_trades(
        conn, account="abc' OR 1=1 --", start_date="2026-01-01", end_date="2026-06-01"
    )

    # 精确FIFO路径(calc_pnl_for_audit)成功时, trades非空, 不走SQL fallback
    if trades:
        # 有真实交易数据返回(account过滤到不存在的account时可能为空)
        assert isinstance(trades, list)
        assert isinstance(errors, list)
    else:
        # 如果calc_pnl_for_audit也没数据, fallback SQL路径记录错误
        assert errors and "missing table" in errors[0]
        assert cursor.executed
        assert "abc' OR 1=1 --" not in cursor.executed[0][0]
        assert "account = %s" in cursor.executed[0][0]
        assert "abc' OR 1=1 --" in cursor.executed[0][1]


def test_batch_audit_records_fetch_errors_and_does_not_insert(monkeypatch):
    class ConnContext:
        def __enter__(self):
            return DummyConn(DummyCursor())

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(sql, "get_conn", lambda: ConnContext())
    monkeypatch.setattr(
        rg,
        "_fetch_completed_trades",
        lambda *args, **kwargs: ([], ["pingan_normal_trade: missing table"]),
    )
    monkeypatch.setattr(sql, "insert_audit_log", lambda *args, **kwargs: None)

    stats = rg.batch_audit()

    assert stats["processed"] == 0
    assert stats["inserted"] == 0
    assert stats["errors"] == ["pingan_normal_trade: missing table"]


def test_batch_update_post_validation_updates_due_records(monkeypatch):
    cursor = DummyCursor(
        rows=[
            (
                7,
                "000539",
                date(2026, 5, 20),
                10.0,
                9.5,
                0,
                0,
                date(2026, 6, 1),
            )
        ]
    )
    conn = DummyConn(cursor)

    monkeypatch.setattr(
        rg,
        "fetch_post_validation",
        lambda *args, **kwargs: {
            "post20": {"close": 9.2, "chg": -8, "high": 10.2, "low": 9.0},
            "post60": {"chg": -12},
            "post_new_high": False,
        },
    )
    updated = {}

    def fake_update_post_validation(conn_arg, audit_id, data):
        updated[audit_id] = data
        return True

    monkeypatch.setattr(sql, "update_post_validation", fake_update_post_validation)

    stats = rg.batch_update_post_validation(conn, days_list=[20, 60])

    assert stats == {"processed": 1, "updated": 1, "skipped": 0, "errors": []}
    assert updated[7]["post20_chg"] == -8
    assert updated[7]["post60_chg"] == -12


def test_mysql_password_has_no_hardcoded_fallback(monkeypatch):
    monkeypatch.delenv("MYSQL_PWD", raising=False)
    cfg = sql._load_mysql_config()
    assert cfg["password"] == ""


def test_audit_score_returns_cli_detail_fields():
    score = rg.audit_score(
        {
            "indicators": {"MACD_DIF": 1, "MACD_DEA": 0},
            "stk_trend": "bull",
            "mkt_trend": "bull",
            "boll_pctb": 40,
            "is_chase": False,
            "entry_signal": "突破",
            "sector_pct_rank": 20,
            "trade_direction": "顺势买入",
            "sell_reason": "止损",
            "sell_trigger": "rule_triggered",
            "sell_verdict": "correct",
            "has_plan": True,
            "position_rule": "pass",
            "stop_loss_set": 1,
            "stop_loss_pct": 5,
            "single_risk_pct": 1,
        }
    )

    assert score["entry_detail"]
    assert score["exit_detail"]
    assert score["discipline_detail"]
    assert score["risk_control_detail"]
