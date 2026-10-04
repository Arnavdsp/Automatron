"""The tenant migration, applied to a real PostgreSQL and attacked as each role.

The application checks ownership itself; these tests prove the database would
refuse a cross-tenant read or write even if the application did not. They start
a throwaway PostgreSQL cluster and are skipped where its binaries are missing.
"""

import os
import pathlib
import shutil
import subprocess
import tempfile
import uuid

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
MIGRATIONS = sorted((ROOT / "supabase" / "migrations").glob("*.sql"))
STUB = ROOT / "tests" / "sql" / "supabase_stub.sql"


def find_pg_bin() -> pathlib.Path | None:
    on_path = shutil.which("initdb")
    if on_path:
        return pathlib.Path(on_path).parent
    for candidate in sorted(pathlib.Path("/usr/lib/postgresql").glob("*/bin"), reverse=True):
        if (candidate / "initdb").is_file():
            return candidate
    return None


PG_BIN = find_pg_bin()
pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(PG_BIN is None, reason="PostgreSQL binaries are not installed"),
]


class Database:
    """A throwaway cluster, driven through psql as one role at a time."""

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root
        self.data = root / "data"
        self.socket = root / "socket"
        self.port = str(20000 + uuid.uuid4().int % 20000)
        # PostgreSQL refuses to run as root, which is what a container usually is.
        self.prefix = ["runuser", "-u", "postgres", "--"] if os.geteuid() == 0 else []

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run([*self.prefix, *args], capture_output=True, text=True,
                              check=check, cwd=self.root)

    def start(self) -> None:
        self.socket.mkdir(parents=True)
        if self.prefix:
            shutil.chown(self.root, "postgres")
            shutil.chown(self.socket, "postgres")
        self.run(str(PG_BIN / "initdb"), "-D", str(self.data), "-U", "postgres", "--auth=trust")
        self.run(str(PG_BIN / "pg_ctl"), "-D", str(self.data), "-w", "-l",
                 str(self.root / "pg.log"), "-o",
                 f"-p {self.port} -k {self.socket} -c listen_addresses=''", "start")

    def stop(self) -> None:
        self.run(str(PG_BIN / "pg_ctl"), "-D", str(self.data), "-m", "immediate", "stop",
                 check=False)

    def psql(self, sql: str, check: bool = True) -> subprocess.CompletedProcess:
        script = self.root / f"{uuid.uuid4().hex}.sql"
        script.write_text(sql, encoding="utf-8")
        if self.prefix:
            shutil.chown(script, "postgres")
        return self.run(str(PG_BIN / "psql"), "-h", str(self.socket), "-p", self.port,
                        "-U", "postgres", "-d", "postgres", "-v", "ON_ERROR_STOP=1",
                        "-qAt", "-f", str(script), check=check)

    def as_user(self, user_id: str | None, sql: str, role: str = "authenticated") -> str:
        """Run sql as a signed-in user (or anon) inside one transaction."""
        claim = user_id or ""
        result = self.psql(
            "begin;\n"
            f"set local role {role};\n"
            f"select set_config('request.jwt.claim.sub', '{claim}', true) \\g /dev/null\n"
            f"{sql}\ncommit;\n",
            check=False,
        )
        if result.returncode != 0:
            raise PermissionError(result.stderr.strip())
        return result.stdout.strip()


@pytest.fixture(scope="module")
def db():
    # Directly under the system temp directory rather than pytest's own, which is
    # private to the invoking user and so unreadable to the postgres account.
    root = pathlib.Path(tempfile.mkdtemp(prefix="automatron-pg-"))
    database = Database(root)
    try:
        database.start()
        database.psql(STUB.read_text(encoding="utf-8"))
        for migration in MIGRATIONS:
            database.psql(migration.read_text(encoding="utf-8"))
        yield database
    except subprocess.CalledProcessError as exc:
        raise AssertionError(f"{exc.cmd[-1]}: {exc.stderr}") from exc
    finally:
        database.stop()
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="module")
def people(db):
    """Three signed-up users, each with the personal organization signup gives them."""
    ids = {}
    for name in ("alice", "bob", "carol"):
        ids[name] = db.psql(
            f"insert into auth.users (email) values ('{name}@example.com') returning id;"
        ).stdout.strip()
        ids[f"{name}_org"] = db.psql(
            "select organization_id from public.organization_members "
            f"where user_id = '{ids[name]}';"
        ).stdout.strip()
    run = str(uuid.uuid4())
    db.as_user(ids["alice"], "insert into public.runs (id, organization_id, sector, "
               f"workflow_id, status, {SEALED_COLUMNS}) values ('{run}', '{ids['alice_org']}', "
               f"'space', 'space.conjunction_triage', 'awaiting_approval', {SEALED_VALUES});")
    ids["alice_run"] = run
    return ids


def new_run(db, user, org, run_id=None):
    run_id = run_id or str(uuid.uuid4())
    db.as_user(user, "insert into public.runs (id, organization_id, sector, workflow_id, "
               f"status, {SEALED_COLUMNS}) values ('{run_id}', '{org}', 'quant', "
               f"'quant.trade_gate', 'queued', {SEALED_VALUES});")
    return run_id


HASH = "a" * 64
# What the application stores: a wrapped run key and sealed values. Their contents
# do not matter here; only that they have the sealed shape the database insists on.
SEALED_COLUMNS = "key_id, wrapped_key, sealed_input"
SEALED_VALUES = "'local:k1', 'd3JhcHBlZC1ydW4ta2V5', 'v1.c2VhbGVk'"
SEALED_PAYLOAD = '{"action": "approve", "sealed": "v1.c2VhbGVk"}'


class TestSignupGivesEachUserTheirOwnOrganization:
    def test_each_user_owns_exactly_one_organization(self, db, people):
        for name in ("alice", "bob", "carol"):
            rows = db.as_user(people[name], "select role from public.organization_members;")
            assert rows == "owner"

    def test_a_user_sees_only_their_own_organization(self, db, people):
        assert db.as_user(people["bob"], "select id from public.organizations;") \
            == people["bob_org"]


class TestRunsStayInsideTheirOrganization:
    def test_the_owner_reads_their_run(self, db, people):
        assert db.as_user(people["alice"], "select id from public.runs;") == people["alice_run"]

    def test_another_user_reads_nothing(self, db, people):
        assert db.as_user(people["bob"], "select count(*) from public.runs;") == "0"
        assert db.as_user(
            people["bob"], f"select count(*) from public.runs where id = '{people['alice_run']}';"
        ) == "0"

    def test_another_user_cannot_file_a_run_under_someone_elses_organization(self, db, people):
        with pytest.raises(PermissionError, match="row-level security"):
            new_run(db, people["bob"], people["alice_org"])

    def test_a_run_cannot_claim_another_creator(self, db, people):
        with pytest.raises(PermissionError, match="row-level security"):
            db.as_user(people["bob"], "insert into public.runs (id, organization_id, created_by, "
                       f"sector, workflow_id, status, {SEALED_COLUMNS}) values "
                       f"('{uuid.uuid4()}', '{people['bob_org']}', '{people['alice']}', "
                       f"'space', 'x', 'queued', {SEALED_VALUES});")

    def test_another_user_cannot_change_its_status(self, db, people):
        db.as_user(people["bob"], "update public.runs set status = 'approved' "
                   f"where id = '{people['alice_run']}';")
        assert db.as_user(people["alice"], "select status from public.runs;") \
            == "awaiting_approval"

    def test_not_even_the_creator_can_move_it_to_another_organization(self, db, people):
        with pytest.raises(PermissionError, match="permission denied"):
            db.as_user(people["alice"], f"update public.runs set organization_id = "
                       f"'{people['bob_org']}' where id = '{people['alice_run']}';")

    def test_the_anonymous_role_reads_nothing_at_all(self, db, people):
        for table in ("runs", "organizations", "organization_members", "audit_entries"):
            with pytest.raises(PermissionError, match="permission denied"):
                db.as_user(None, f"select count(*) from public.{table};", role="anon")


class TestTheAuditTrail:
    def test_an_entry_is_readable_only_inside_its_organization(self, db, people):
        db.as_user(people["alice"], "insert into public.audit_entries (run_id, organization_id, "
                   f"payload, prev_hash, hash) values ('{people['alice_run']}', "
                   f"'{people['alice_org']}', '{SEALED_PAYLOAD}', '{'0' * 64}', "
                   f"'{HASH}');")
        assert db.as_user(people["alice"], "select count(*) from public.audit_entries;") == "1"
        assert db.as_user(people["bob"], "select count(*) from public.audit_entries;") == "0"

    def test_an_entry_cannot_file_one_tenants_run_under_another(self, db, people):
        """Bob files an entry about Alice's run under his own organization, which would
        make a record of her run readable to him. The pairing is refused."""
        with pytest.raises(PermissionError, match="foreign key"):
            db.as_user(people["bob"], "insert into public.audit_entries (run_id, "
                       f"organization_id, payload, prev_hash, hash) values "
                       f"('{people['alice_run']}', '{people['bob_org']}', '{SEALED_PAYLOAD}', "
                       f"'{HASH}', '{HASH}');")

    def test_an_entry_cannot_be_written_into_another_organization(self, db, people):
        with pytest.raises(PermissionError, match="row-level security"):
            db.as_user(people["bob"], "insert into public.audit_entries (run_id, "
                       f"organization_id, payload, prev_hash, hash) values "
                       f"('{people['alice_run']}', '{people['alice_org']}', '{SEALED_PAYLOAD}', "
                       f"'{HASH}', '{HASH}');")

    def test_no_one_can_rewrite_it_not_even_the_database_owner(self, db, people):
        for statement in ("update public.audit_entries set payload = '{}';",
                          "delete from public.audit_entries;"):
            result = db.psql(statement, check=False)
            assert result.returncode != 0
            assert "append-only" in result.stderr

    def test_a_decided_run_cannot_be_deleted_out_from_under_its_record(self, db, people):
        result = db.psql(f"delete from public.runs where id = '{people['alice_run']}';",
                         check=False)
        assert result.returncode != 0


class TestMembership:
    def test_an_owner_can_share_their_organization(self, db, people):
        org = people["carol_org"]
        run = new_run(db, people["carol"], org)
        db.as_user(people["carol"], "insert into public.organization_members "
                   f"(organization_id, user_id, role) values ('{org}', '{people['bob']}', "
                   "'member');")
        assert db.as_user(people["bob"], f"select id from public.runs "
                          f"where organization_id = '{org}';") == run

    def test_a_member_cannot_invite_others(self, db, people):
        with pytest.raises(PermissionError, match="row-level security"):
            db.as_user(people["bob"], "insert into public.organization_members "
                       f"(organization_id, user_id, role) values ('{people['carol_org']}', "
                       f"'{people['alice']}', 'owner');")

    def test_no_one_can_add_themselves_to_an_organization(self, db, people):
        with pytest.raises(PermissionError, match="row-level security"):
            db.as_user(people["alice"], "insert into public.organization_members "
                       f"(organization_id, user_id, role) values ('{people['bob_org']}', "
                       f"'{people['alice']}', 'owner');")


class TestUploads:
    def test_files_are_readable_only_inside_their_organization(self, db, people):
        path = f"{people['alice_org']}/{people['alice_run']}/report.pdf"
        db.as_user(people["alice"], "insert into storage.objects (bucket_id, name) "
                   f"values ('run-uploads', '{path}');")
        assert db.as_user(people["alice"], "select count(*) from storage.objects "
                          f"where name = '{path}';") == "1"
        assert db.as_user(people["bob"], "select count(*) from storage.objects "
                          f"where name = '{path}';") == "0"

    def test_uploading_into_another_organization_is_refused(self, db, people):
        with pytest.raises(PermissionError, match="row-level security"):
            db.as_user(people["bob"], "insert into storage.objects (bucket_id, name) values "
                       f"('run-uploads', '{people['alice_org']}/x/evil.pdf');")

    def test_a_malformed_path_is_refused_rather_than_raising(self, db, people):
        with pytest.raises(PermissionError, match="row-level security"):
            db.as_user(people["bob"], "insert into storage.objects (bucket_id, name) values "
                       "('run-uploads', 'not-a-uuid/x/file.pdf');")

    def test_the_bucket_is_private(self, db, people):
        assert db.psql("select public from storage.buckets where id = 'run-uploads';"
                       ).stdout.strip() == "f"


class TestOnlyCiphertextIsStored:
    """The application seals run content before storing it. The database holds it to
    that, so plaintext cannot reach these columns even through a bug."""

    def insert(self, db, people, **overrides):
        values = {"key_id": "'local:k1'", "wrapped_key": "'d3JhcHBlZC1ydW4ta2V5'",
                  "sealed_input": "'v1.c2VhbGVk'", **overrides}
        db.as_user(people["alice"], "insert into public.runs (id, organization_id, sector, "
                   f"workflow_id, status, key_id, wrapped_key, sealed_input) values "
                   f"('{uuid.uuid4()}', '{people['alice_org']}', 'space', 'x', 'queued', "
                   f"{values['key_id']}, {values['wrapped_key']}, {values['sealed_input']});")

    def test_a_sealed_run_is_accepted(self, db, people):
        self.insert(db, people)

    def test_a_plaintext_request_is_refused(self, db, people):
        with pytest.raises(PermissionError, match="check constraint"):
            self.insert(db, people, sealed_input="'Triage CDM for SAT-123 tonight'")

    def test_a_run_without_its_key_is_refused(self, db, people):
        with pytest.raises(PermissionError, match="null value|check constraint"):
            self.insert(db, people, wrapped_key="null")

    def test_an_unrecognised_key_reference_is_refused(self, db, people):
        with pytest.raises(PermissionError, match="check constraint"):
            self.insert(db, people, key_id="'plaintext'")

    def test_a_plaintext_result_is_refused(self, db, people):
        with pytest.raises(PermissionError, match="check constraint"):
            db.as_user(people["alice"], "update public.runs set sealed_result = "
                       f"'the brief in the clear' where id = '{people['alice_run']}';")

    def test_the_creator_can_record_a_sealed_result(self, db, people):
        db.as_user(people["alice"], "update public.runs set sealed_result = 'v1.cmVzdWx0' "
                   f"where id = '{people['alice_run']}';")

    def test_the_input_and_key_cannot_be_rewritten(self, db, people):
        for column in ("sealed_input", "wrapped_key", "key_id"):
            with pytest.raises(PermissionError, match="permission denied"):
                db.as_user(people["alice"], f"update public.runs set {column} = "
                           f"'v1.b3RoZXI' where id = '{people['alice_run']}';")

    def test_an_audit_payload_must_be_sealed(self, db, people):
        with pytest.raises(PermissionError, match="check constraint"):
            db.as_user(people["alice"], "insert into public.audit_entries (run_id, "
                       "organization_id, payload, prev_hash, hash) values "
                       f"('{people['alice_run']}', '{people['alice_org']}', "
                       "'{\"action\": \"approve\", \"notes\": \"in the clear\"}', "
                       f"'{HASH}', '{HASH}');")
