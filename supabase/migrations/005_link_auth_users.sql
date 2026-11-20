-- 005: link the two login users to their customer rows.
-- Looks the user up by email, so no ids are stored in the repo.
-- On a fresh project with no such users, both updates change nothing.
update customers set auth_user_id = (select id from auth.users where email = 'cust001@example.com') where customer_id = 'cust_001';
update customers set auth_user_id = (select id from auth.users where email = 'cust002@example.com') where customer_id = 'cust_002';