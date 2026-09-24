CREATE TABLE dim_player (
  player_id VARCHAR(20) PRIMARY KEY,
  register_date DATE NOT NULL,
  region VARCHAR(30) NOT NULL,
  platform VARCHAR(20) NOT NULL,
  acquisition_channel VARCHAR(30) NOT NULL
);

CREATE TABLE dim_game (
  game_id VARCHAR(20) PRIMARY KEY,
  game_name VARCHAR(100) NOT NULL,
  genre VARCHAR(30) NOT NULL
);

CREATE TABLE dim_date (
  date_id INT PRIMARY KEY,
  year INT NOT NULL,
  quarter VARCHAR(2) NOT NULL,
  month INT NOT NULL,
  day INT NOT NULL
);

CREATE TABLE fact_player_daily (
  event_id VARCHAR(20) PRIMARY KEY,
  player_id VARCHAR(20) NOT NULL,
  game_id VARCHAR(20) NOT NULL,
  date_id INT NOT NULL,
  login_count INT NOT NULL,
  online_minutes INT NOT NULL,
  level_reached INT NOT NULL,
  is_active TINYINT NOT NULL
);

CREATE TABLE fact_payment (
  payment_id VARCHAR(20) PRIMARY KEY,
  player_id VARCHAR(20) NOT NULL,
  game_id VARCHAR(20) NOT NULL,
  date_id INT NOT NULL,
  amount DECIMAL(10,2) NOT NULL,
  currency VARCHAR(10) NOT NULL
);

CREATE TABLE fact_level_event (
  event_id VARCHAR(20) PRIMARY KEY,
  player_id VARCHAR(20) NOT NULL,
  game_id VARCHAR(20) NOT NULL,
  date_id INT NOT NULL,
  level_id VARCHAR(20) NOT NULL,
  attempts INT NOT NULL,
  passed TINYINT NOT NULL,
  duration_seconds INT NOT NULL
);
