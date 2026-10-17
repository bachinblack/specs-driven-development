-- Exported after the migrations are applied. Never edit by hand.

CREATE TABLE pokemon_type (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE pokemon (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    type_id INT NOT NULL REFERENCES pokemon_type (id),
    level INT,
    description TEXT
);

CREATE INDEX idx_pokemon_type_id ON pokemon (type_id);
