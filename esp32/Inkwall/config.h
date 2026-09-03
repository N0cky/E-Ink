#pragma once

// Zentraler Einstiegspunkt fuer die Firmware-Konfiguration.
// Reihenfolge:
// 1. optionale lokale Overrides aus config.private.h
// 2. fehlende Standardwerte aus config.example.h

#if __has_include("config.private.h")
#include "config.private.h"
#endif

#include "config.example.h"
