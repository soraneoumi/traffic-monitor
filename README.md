# traffic-monitor
A script for calculating port traffics usage with nftables.

## Database Structure

### Table: `traffic_daily`

This table saves daily traffic stats.

| Column       | Description                                      |
|--------------|--------------------------------------------------|
| `port`       | The monitored port number                        |
| `rule`       | Rule name (such as `input_tcp`, `output_udp`, etc.) |
| `report_date`| Date (format: `YYYY-MM-DD`)                      |
| `base`       | nftables counter at the start of the day         |
| `accumulated`| Total counter after adding today's changes       |
| `last_raw`   | Last raw counter from nft                        |
| `last_update`| Last updated time                                |

**Primary Key**: `(port, rule, report_date)`

---

### Table: `traffic_monthly`

This table saves total traffic of each month.

| Column         | Description                                 |
|----------------|---------------------------------------------|
| `port`         | Port number                                 |
| `rule`         | Rule name                                   |
| `report_month` | Month (format: `YYYY-MM`)                   |
| `total`        | Total traffic of this month (sum of days)   |
| `last_update`  | Last updated time                           |

**Primary Key**: `(port, rule, report_month)`

---
