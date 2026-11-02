"""pytest 公共夹具。

每个测试用例用独立的 SQLite 临时文件，
避免用例之间互相污染，也避免依赖外部 MySQL。
"""

import pytest

from app import create_app


@pytest.fixture()
def app(tmp_path):
    db_file = (tmp_path / "test.db").as_posix()
    application = create_app(
        {
            "TESTING": True,
            "STARTUP_DELAY_SECONDS": 0.0,
            "APP_VERSION": "test-1.0.0",
            "ENV_NAME": "test",
            "DATABASE_URL": "sqlite:///" + db_file,
            "AUTO_CREATE_TABLES": True,
            "READYZ_CHECK_DB": True,
        }
    )
    yield application


@pytest.fixture()
def client(app):
    with app.test_client() as c:
        yield c
