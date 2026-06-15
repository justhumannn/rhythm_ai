# Rhythm AI ERD

```mermaid
erDiagram
    WAV_SONGS ||--o{ CHART_DATA : "has"

    WAV_SONGS {
        INTEGER id PK
        VARCHAR_1024 youtube_url UK
        VARCHAR_512 title
        VARCHAR_2048 wav_path
        DATETIME created_at
    }

    CHART_DATA {
        INTEGER id PK
        INTEGER song_id FK
        VARCHAR_160 name
        VARCHAR_256 password_hash
        TEXT key_bindings_json
        TEXT chart_json
        VARCHAR_64 difficulty
        FLOAT tap_ratio
        FLOAT hold_ratio
        INTEGER key_count
        FLOAT bpm
        FLOAT tap_threshold
        FLOAT hold_threshold
        DATETIME created_at
    }
```

## Relationship

- `WAV_SONGS.id` -> `CHART_DATA.song_id`
- One song can have zero or more charts.
- Deleting a song deletes its associated charts through the SQLAlchemy relationship.
- `WAV_SONGS.youtube_url` is unique.
