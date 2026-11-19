-- SQLite secondary indexes already include rowid as their final key.
CREATE INDEX registry_observations_connection ON registry_observations(connection_id);

CREATE INDEX registry_inventory_latest ON registry_observations(connection_id)
WHERE json_extract(record,'$.operation')='inventory';

CREATE INDEX registry_inventory_usable ON registry_observations(connection_id)
WHERE json_extract(record,'$.operation')='inventory'
AND json_extract(record,'$.state') IN ('observed','partial');

CREATE INDEX registry_inventory_complete ON registry_observations(connection_id)
WHERE json_extract(record,'$.operation')='inventory'
AND json_extract(record,'$.state')='observed';

-- Keep the recent diagnostic tail and the inventory facts needed to retain a
-- successful snapshot through failed or partial subsequent discoveries.
WITH recent AS (
    SELECT rowid AS observation_row,
           row_number() OVER (PARTITION BY connection_id ORDER BY rowid DESC) AS position
    FROM registry_observations
), anchors AS (
    SELECT max(rowid) AS observation_row FROM registry_observations
    WHERE json_extract(record,'$.operation')='inventory' GROUP BY connection_id
    UNION
    SELECT max(rowid) FROM registry_observations
    WHERE json_extract(record,'$.operation')='inventory'
      AND json_extract(record,'$.state') IN ('observed','partial') GROUP BY connection_id
    UNION
    SELECT max(rowid) FROM registry_observations
    WHERE json_extract(record,'$.operation')='inventory'
      AND json_extract(record,'$.state')='observed' GROUP BY connection_id
)
DELETE FROM registry_observations
WHERE rowid IN (SELECT observation_row FROM recent WHERE position > 20)
  AND rowid NOT IN (SELECT observation_row FROM anchors);
