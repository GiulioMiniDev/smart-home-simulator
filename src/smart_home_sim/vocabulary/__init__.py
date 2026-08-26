"""The editable vocabulary: what the resident can do, and what the flat is made of.

Deliberately empty of eager imports. `defaults` reads the very tables that `sensors.service` and
`simulation.service` own, and those modules now read the pack back — so importing `defaults` here
would make `from smart_home_sim.vocabulary import views` close a cycle through the sensor
projector. Callers import the submodule they want.
"""
