-- Open access: there are no staff or admin accounts any more. Every account is an ordinary user
-- who can see only their own saved results. Any account created by an older version becomes an ordinary user.
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
UPDATE users SET role = 'user';
ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role = 'user');
