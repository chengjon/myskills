# kline_15min 缓存表

## DDL

```sql
CREATE TABLE IF NOT EXISTS kline_15min (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    stock_code   VARCHAR(10)   NOT NULL COMMENT '股票代码如002195',
    kline_date   DATETIME      NOT NULL COMMENT 'K线时间 2026-05-29 09:30:00',
    open         DECIMAL(10,3) NOT NULL,
    high         DECIMAL(10,3) NOT NULL,
    low          DECIMAL(10,3) NOT NULL,
    close_price  DECIMAL(10,3) NOT NULL COMMENT '收盘价(避保留字close)',
    volume       BIGINT        NOT NULL COMMENT '成交量',
    fetched_at   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '拉取时间',
    UNIQUE KEY uk_stock_date (stock_code, kline_date),
    KEY idx_stock (stock_code),
    KEY idx_fetched (fetched_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='15分钟K线缓存';
```

## 缓存策略

- `fetch_15min_kline(code)` → 查 kline_15min → 有则返回 → 无则调新浪API → INSERT IGNORE写入 → 返回
- `--refresh-cache`: 强制跳过DB缓存，从API重新拉取(INSERT IGNORE不删旧数据，只追加新K线)
- 如需全量刷新某股票: `DELETE FROM kline_15min WHERE stock_code = '002195'` 再 `--refresh-cache`
- 注意列名 `close_price` (非 `close`，避MySQL保留字)

## 数据规模

- 111只股票 × 5000条/股 = ~555,000行
- 时间范围: 2025-02-05 ~ 最新交易日
- 单次INSERT IGNORE批量写入约5000行/股，耗时<1s

## 性能

| 模式 | 939笔耗时 | API调用次数 |
|------|----------|------------|
| 纯DB缓存 | 2m41s | 0 |
| API+写缓存 | 5m02s | 111 |
