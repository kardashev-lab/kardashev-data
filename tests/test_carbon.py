import pytest
from api.routes.carbon import carbon_intensity, emission_factor


class TestEmissionFactor:
    def test_coal(self):
        assert emission_factor("Coal") == 2228.0

    def test_natural_gas_underscore(self):
        assert emission_factor("Natural_Gas") == 899.0

    def test_natural_gas_space(self):
        assert emission_factor("Natural Gas") == 899.0

    def test_nuclear(self):
        assert emission_factor("Nuclear") == 0.0

    def test_wind(self):
        assert emission_factor("Wind") == 0.0

    def test_solar(self):
        assert emission_factor("Solar") == 0.0

    def test_hydro(self):
        assert emission_factor("Hydro") == 0.0

    def test_small_hydro(self):
        assert emission_factor("Small_hydro") == 0.0

    def test_geothermal(self):
        assert emission_factor("Geothermal") == 38.0

    def test_biomass(self):
        assert emission_factor("Biomass") == 1500.0

    def test_wood(self):
        assert emission_factor("Wood") == 1500.0

    def test_other_renewables(self):
        assert emission_factor("Other Renewables") == 0.0

    def test_imports(self):
        assert emission_factor("Imports") == 767.0

    def test_other(self):
        assert emission_factor("Other") == 767.0

    def test_petroleum(self):
        assert emission_factor("Petroleum") == 1555.0

    def test_oil(self):
        assert emission_factor("Oil") == 1555.0


class TestEmissionFactorNercCodes:
    """ISONE and EIA-sourced feeds use NERC abbreviations instead of full names."""

    def test_ng(self):
        assert emission_factor("NG") == 899.0

    def test_nuc(self):
        assert emission_factor("NUC") == 0.0

    def test_wnd(self):
        assert emission_factor("WND") == 0.0

    def test_sun(self):
        assert emission_factor("SUN") == 0.0

    def test_wat(self):
        assert emission_factor("WAT") == 0.0

    def test_ps(self):
        assert emission_factor("PS") == 0.0

    def test_snb(self):
        assert emission_factor("SNB") == 0.0

    def test_bat(self):
        assert emission_factor("BAT") == 0.0

    def test_oth(self):
        assert emission_factor("OTH") == 767.0

    def test_oil_code(self):
        assert emission_factor("OIL") == 1555.0

    def test_case_insensitive(self):
        assert emission_factor("nuc") == emission_factor("NUC") == 0.0
        assert emission_factor("ng") == emission_factor("NG") == 899.0


class TestEmissionFactorFallback:
    def test_unknown_fuel(self):
        assert emission_factor("SomeUnknownFuel") == 767.0

    def test_empty_string(self):
        assert emission_factor("") == 767.0


class TestCarbonIntensity:
    def test_pure_gas(self):
        assert carbon_intensity([("Natural Gas", 1000.0)]) == pytest.approx(899.0)

    def test_pure_solar(self):
        assert carbon_intensity([("Solar", 5000.0)]) == pytest.approx(0.0)

    def test_mixed_gas_and_solar(self):
        mix = [("Natural Gas", 5000.0), ("Solar", 5000.0)]
        assert carbon_intensity(mix) == pytest.approx(449.5)

    def test_weighted_average(self):
        mix = [
            ("Natural Gas", 5000.0),
            ("Solar", 4000.0),
            ("Wind", 2000.0),
            ("Nuclear", 2000.0),
        ]
        assert carbon_intensity(mix) == pytest.approx(5000 * 899.0 / 13000, rel=1e-6)

    def test_nerc_codes(self):
        mix = [("NG", 3000.0), ("NUC", 1000.0), ("WND", 500.0)]
        assert carbon_intensity(mix) == pytest.approx(3000 * 899.0 / 4500)

    def test_zero_mw_rows_excluded(self):
        assert carbon_intensity([("Coal", 1000.0), ("Solar", 0.0)]) == pytest.approx(2228.0)

    def test_empty_returns_none(self):
        assert carbon_intensity([]) is None

    def test_all_zero_mw_returns_none(self):
        assert carbon_intensity([("Solar", 0.0), ("Wind", 0.0)]) is None

    def test_pure_coal(self):
        assert carbon_intensity([("Coal", 10000.0)]) == pytest.approx(2228.0)

    def test_imports_use_national_average(self):
        assert carbon_intensity([("Imports", 1000.0)]) == pytest.approx(767.0)
