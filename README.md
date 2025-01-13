## Database Schema

CREATE TABLE guilds (
  id BIGINT PRIMARY KEY,
  last_channel_id BIGINT
);
  
CREATE TABLE members (
  id BIGINT PRIMARY KEY
);

CREATE TABLE user_settings (
  user_id BIGINT PRIMARY KEY,
  volume INTEGER DEFAULT 100,
  filters TEXT DEFAULT '',
  last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT volume_range CHECK (volume BETWEEN 0 AND 1000),
  CONSTRAINT fk_user_settings_member FOREIGN KEY (user_id) REFERENCES members(id) ON DELETE CASCADE
);

CREATE TABLE playlists (
  id UUID PRIMARY KEY DEFAULT uuid(),
  user_id BIGINT,
  name TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  is_public BOOLEAN DEFAULT false,
  CONSTRAINT fk_playlists_member FOREIGN KEY (user_id) REFERENCES members(id) ON DELETE CASCADE
);

CREATE TABLE tracks (
  id UUID PRIMARY KEY DEFAULT uuid(),
  playlist_id UUID,
  url TEXT NOT NULL,
  title TEXT NOT NULL,
  artist TEXT,
  duration INTEGER,
  added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  position INTEGER,
  CONSTRAINT fk_tracks_playlist FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
);

-- CREATE INDEX idx_user_settings_user_id ON user_settings(user_id);
-- CREATE INDEX idx_playlists_user_id ON playlists(user_id);
-- CREATE INDEX idx_tracks_playlist_id ON tracks(playlist_id);