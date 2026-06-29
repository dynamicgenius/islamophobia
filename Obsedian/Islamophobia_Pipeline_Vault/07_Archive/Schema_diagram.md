# Database Schema (v3)

## Tables

**sources**
- source_id (PK) · source_name · source_type · source_weight · url · active · last_fetched_at

**incidents**
- incident_id (PK) · source_id (FK) · title · summary · content · incident_type · verified
- published_at · reported_at · location_text · latitude · longitude
- relevance_score · confidence · event_flag · conflict_flag · protest_flag · far_right_flag · offline_flag · online_flag

**daily_metrics**
- day (PK) · source_id (PK) · total_items · total_incidents · verified_incidents · avg_confidence · avg_relevance · online_share · offline_share

## Key Relationships

- sources 1:N incidents
- incidents 1:N incident_tags
- daily_metrics aggregates incidents by day
