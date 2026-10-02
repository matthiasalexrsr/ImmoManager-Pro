# Private installation and first-owner setup

ImmoManager serves one private installation with explicitly assigned portfolio
access. Owners assign either all portfolios or a selected set in Settings → Users.
New non-owner accounts default to an empty selected set until access is assigned.
Roles separately control write and administrative actions. Lists, direct IDs,
searches, references, reports, exports and private files apply the current portfolio
scope; a rights change applies to an already issued access token immediately.
Installation-wide administration requires an appropriate role and all-portfolio
access. A selected manager can still edit their own preferences. Portfolio access
does not itself create a tenant portal or separate independent organizations.

Start a new installation without demo data and open its local address, for example
`http://127.0.0.1:8000`. The login page checks `/api/v1/auth/setup-status` and presents
the initial-owner form only while the installation has no users and no completed
setup marker. `POST /api/v1/auth/setup` is restricted to a loopback peer, loopback
Host and same local Origin. The database's unique setup marker and owner account
are committed in one transaction, so concurrent requests create one owner. The
marker survives account deletion. Existing installations and seeded demo accounts
already have setup closed.

Public `/auth/register` is disabled. Owners approve accounts using authenticated
`POST /api/v1/auth/users` with username, email, full_name, password and a supported
role. Managers can manage existing users under the existing permissions but cannot
approve new accounts or assign roles. Expose a new server beyond loopback only
after completing local setup; a remote reverse proxy cannot perform first setup.
SQLite startup creates the additive auth table automatically; managed databases
must run `alembic upgrade head` before deployment.

## Two-factor authentication

In Settings → Personal, each user can enroll an authenticator using the displayed
secret or `otpauth://` URI, then enter a valid six-digit code to enable 2FA. The
secret remains pending until confirmed. Repeating setup resumes that pending
enrollment and cannot replace an enabled secret. Login asks for the code after
password validation; incorrect codes count toward the login lockout. Disabling
2FA also requires a valid current code. Secret values are never returned by profile
or status endpoints. Record the account ID displayed in the 2FA section for local
recovery.

## Offline recovery for local SQLite installations

If the authenticator is lost, the person who controls the installation files can
reset one recorded account ID locally. Stop ImmoManager first, preserve a database
backup, and run from the project directory:

```powershell
python scripts/reset_2fa.py --data-dir "C:\path\to\installation-data" --user-id "recorded-account-id" --reason "Authenticator lost; owner verified locally"
```

The command opens only the existing `immo_manager.db` in that directory, resets
only that ID, and records the reason and target username in the database audit log
in the same transaction. Unknown IDs, missing databases and missing reasons make
no changes. It has no network endpoint and no universal recovery password. Secure
the data directory with operating-system permissions. PostgreSQL recovery remains
an installation administrator's database operation with equivalent auditing.
