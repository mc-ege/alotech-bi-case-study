-- Task 2.1: expose only the three requested user contact fields.
CREATE OR REPLACE VIEW `alotech-bi-case-study.alotech_shared.v_users_contact`
OPTIONS (
  description = 'Restricted user contact projection for the AloTech BI case study.'
)
AS
SELECT
  first_name,
  last_name,
  email
FROM `alotech-bi-case-study.alotech_raw.users`;
