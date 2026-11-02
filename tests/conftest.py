"""Tests never touch the real database (data/sanae.db): MemoryStore refuses it while SANAE_LAB is set."""
import os

os.environ["SANAE_LAB"] = "1"
