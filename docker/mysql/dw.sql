SET NAMES utf8mb4;
CREATE DATABASE IF NOT EXISTS dw DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
USE dw;

DROP TABLE IF EXISTS fact_level_event;
DROP TABLE IF EXISTS fact_payment;
DROP TABLE IF EXISTS fact_player_daily;
DROP TABLE IF EXISTS dim_date;
DROP TABLE IF EXISTS dim_game;
DROP TABLE IF EXISTS dim_player;

CREATE TABLE dim_player (
  player_id VARCHAR(20) PRIMARY KEY,
  register_date DATE NOT NULL,
  region VARCHAR(30) NOT NULL,
  platform VARCHAR(20) NOT NULL,
  acquisition_channel VARCHAR(30) NOT NULL
);
INSERT INTO dim_player VALUES
('P001','2026-09-01','华北','iOS','自然量'),
('P002','2026-09-02','华东','Android','短视频广告'),
('P003','2026-09-02','华北','PC','社区推荐'),
('P004','2026-09-03','华南','Android','应用商店');

CREATE TABLE dim_game (
  game_id VARCHAR(20) PRIMARY KEY,
  game_name VARCHAR(100) NOT NULL,
  genre VARCHAR(30) NOT NULL
);
INSERT INTO dim_game VALUES
('G001','星海远征','策略'),
('G002','极速竞技场','竞速');

CREATE TABLE dim_date (
  date_id INT PRIMARY KEY,
  year INT NOT NULL,
  quarter VARCHAR(2) NOT NULL,
  month INT NOT NULL,
  day INT NOT NULL
);
INSERT INTO dim_date VALUES
(20260918,2026,'Q3',9,18),(20260919,2026,'Q3',9,19),
(20260920,2026,'Q3',9,20),(20260921,2026,'Q3',9,21);

CREATE TABLE fact_player_daily (
  event_id VARCHAR(20) PRIMARY KEY,
  player_id VARCHAR(20) NOT NULL,
  game_id VARCHAR(20) NOT NULL,
  date_id INT NOT NULL,
  login_count INT NOT NULL,
  online_minutes INT NOT NULL,
  level_reached INT NOT NULL,
  is_active TINYINT NOT NULL,
  INDEX idx_daily_date (date_id), INDEX idx_daily_player (player_id)
);
INSERT INTO fact_player_daily VALUES
('A001','P001','G001',20260918,2,65,8,1),
('A002','P002','G001',20260918,1,31,4,1),
('A003','P001','G001',20260919,3,82,10,1),
('A004','P003','G002',20260919,1,24,3,1),
('A005','P004','G001',20260920,2,50,6,1),
('A006','P001','G001',20260921,2,70,12,1);

CREATE TABLE fact_payment (
  payment_id VARCHAR(20) PRIMARY KEY,
  player_id VARCHAR(20) NOT NULL,
  game_id VARCHAR(20) NOT NULL,
  date_id INT NOT NULL,
  amount DECIMAL(10,2) NOT NULL,
  currency VARCHAR(10) NOT NULL,
  INDEX idx_payment_date (date_id), INDEX idx_payment_player (player_id)
);
INSERT INTO fact_payment VALUES
('PAY001','P001','G001',20260918,30.00,'CNY'),
('PAY002','P002','G001',20260918,6.00,'CNY'),
('PAY003','P001','G001',20260920,68.00,'CNY'),
('PAY004','P003','G002',20260921,18.00,'CNY');

CREATE TABLE fact_level_event (
  event_id VARCHAR(20) PRIMARY KEY,
  player_id VARCHAR(20) NOT NULL,
  game_id VARCHAR(20) NOT NULL,
  date_id INT NOT NULL,
  level_id VARCHAR(20) NOT NULL,
  attempts INT NOT NULL,
  passed TINYINT NOT NULL,
  duration_seconds INT NOT NULL,
  INDEX idx_level_date (date_id), INDEX idx_level_id (level_id)
);
INSERT INTO fact_level_event VALUES
('L001','P001','G001',20260918,'LEVEL_08',1,1,210),
('L002','P002','G001',20260918,'LEVEL_05',3,0,480),
('L003','P001','G001',20260919,'LEVEL_10',2,1,390),
('L004','P004','G001',20260920,'LEVEL_07',4,0,520),
('L005','P003','G002',20260921,'TRACK_03',2,1,175);
