#!/usr/bin/env python3
"""
GRVT BTC网格交易策略配置文件
"""
#测试
# # ========== GRVT API 配置 ==========
# GRVT_CONFIG = {
#     "api_key": "",
#     "private_key": "",
#     "trading_account_id": "",
#     "env": "testnet",
#     "symbol": "BTC_USDT_Perp"
# }
#186.59-0.30
GRVT_CONFIG = {
    "api_key": "",
    "private_key": "",
    "trading_account_id": "",
    "env": "prod",
    "symbol": "BTC_USDT_Perp"
}

# ========== 基础交易配置 ==========
TRADING_CONFIG = {
    "MIN_ORDER_INTERVAL": 0.1,
    "ORDER_COOLDOWN": 0.1,
    "MONITOR_INTERVAL": 1,
    "MAX_PROCESSED_ORDERS": 100,
    "RISK_COOLDOWN_MINUTES": 15,
    "CHECK_INTERVAL_RISK": 10,
    "PRICE_FETCH_INTERVAL": 2,
    "ORDER_SIZE": 0.005,  # 开单大小 - 关键：从0.002改为0.005
    "ORDER_STATUS_CHECK_INTERVAL": 2
}

# ========== 网格策略核心配置 ==========
GRID_STRATEGY_CONFIG = {
    "TOTAL_ORDERS": 18,  # 总订单数
    "WINDOW_PERCENT": 0.12,  # 窗口宽度百分比
    "SELL_RATIO": 0.5,  # 卖单比例（买单比例 = 1 - SELL_RATIO）
    # 注意：删除 BUY_RATIO，使用 1 - SELL_RATIO 计算
    "BASE_PRICE_INTERVAL": 15.0,  # 基础价格间隔(USD)
    "SAFE_GAP": 20.0,  # 安全间距
    "MAX_DRIFT_BUFFER": 2000.0,  # 最大漂移缓冲
    "MIN_VALID_PRICE": 10000.0,  # 最小有效价格
    "MAX_MULTIPLIER": 15,  # 最大开仓倍数（与JS版本一致）

    # RSI/ADX配置 (需要外部数据源)
    "RSI_MIN": 30,
    "RSI_MAX": 70,
    "ADX_TREND_THRESHOLD": 25,
    "ADX_STRONG_TREND": 30
}

# ========== 数据源配置 ==========
DATA_SOURCE_CONFIG = {
    "rsi_adx_enabled": True,  # 暂时禁用，先解决订单问题
    "price_source": "grvt",
    "indicator_source": "binance",
}

# ========== 币安 API 配置 ==========
BINANCE_CONFIG = {
    "api_key": "",
    "api_secret": "",
    "symbol": "BTC/USDT",
    "timeframe": "15m",
    "ohlcv_limit": 500,
    "enableRateLimit": True,
    "options": {'defaultType': 'future'}
}

# ========== 技术指标计算配置 ==========
INDICATOR_CONFIG = {
    "enabled": True,
    "rsi_period": 14,
    "adx_period": 14,
    "rsi_oversold": 30,
    "rsi_overbought": 70,
    "adx_trend_threshold": 25,
    "adx_strong_trend": 30,
    "fetch_timeout": 10,
    "cache_seconds": 30,

}
