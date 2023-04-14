import pytest

from pbench.server.database.database import Database
from pbench.server.database.models import TZDateTime
from pbench.server.database.models.api_keys import APIKey
from pbench.test.unit.server import DRB_USER_ID
from pbench.test.unit.server.database import FakeSession


class TestAPIKeyDB:

    session = None

    # Current time to encode in the payload
    current_utc = TZDateTime.current_time()

    @pytest.fixture()
    def fake_db(self, monkeypatch, server_config):
        """
        Fixture to mock a DB session for testing.

        We patch the SQLAlchemy db_session to our fake session. We also store a
        server configuration object directly on the Database.Base (normally
        done during DB initialization) because that can't be monkeypatched.
        """
        __class__.session = FakeSession(APIKey)
        monkeypatch.setattr(Database, "db_session", __class__.session)
        Database.Base.config = server_config
        yield monkeypatch

    def test_construct(self, db_session, create_drb_user, create_user):
        """Test api_key constructor"""

        api_key = APIKey(
            api_key="generated_api_key",
            user=create_user,
        )
        api_key.add()

        assert api_key.api_key == "generated_api_key"
        assert api_key.user.id is create_user.id

    def test_query(self, db_session, pbench_drb_api_key):
        """Test that we can able to query api_key in the table"""

        key = APIKey.query(pbench_drb_api_key)
        assert key.api_key == pbench_drb_api_key
        assert key.user.id == DRB_USER_ID
        assert key.user.username == "drb"

    def test_delete(self, db_session, create_user, pbench_drb_api_key):
        """Test that we can delete an api_key"""

        # we can find it
        key = APIKey.query(pbench_drb_api_key)
        assert key.api_key == pbench_drb_api_key

        APIKey.delete(pbench_drb_api_key)
        assert APIKey.query(pbench_drb_api_key) is None
