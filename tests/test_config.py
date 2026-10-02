"""针对 src.config 的单元测试"""

import os
from src.config import AppConfig, BrowserConfig, DelayConfig, LogConfig, SafetyConfig, config


def test_default_config():
    """测试默认配置项是否符合头歌规范"""
    assert config.browser.port == 9222
    assert config.browser.target_domain == "educoder.net"
    assert config.browser.cdp_url == "http://127.0.0.1:9222"

    # 延时默认配置
    assert config.delay.click_delay == (0.5, 1.5)
    assert config.delay.input_delay == (0.05, 0.2)
    assert config.delay.submit_delay == (1.5, 3.0)

    # 安全风控配置 (连续 3 次报错无变化停止)
    assert config.safety.max_consecutive_unchanged_errors == 3


def test_custom_config_override():
    """测试配置类的实例化与自定义覆盖"""
    custom_browser = BrowserConfig(port=9333, host="192.168.1.100")
    assert custom_browser.cdp_url == "http://192.168.1.100:9333"

    custom_app = AppConfig(
        browser=custom_browser,
        delay=DelayConfig(click_delay=(1.0, 2.0)),
        log=LogConfig(level="DEBUG", json_mode=True),
    )
    assert custom_app.browser.port == 9333
    assert custom_app.delay.click_delay == (1.0, 2.0)
    assert custom_app.log.level == "DEBUG"
    assert custom_app.log.json_mode is True
