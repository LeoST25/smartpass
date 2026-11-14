import pytest


@pytest.fixture
def otp_payload_completo():
    return {
        "data": {
            "planConnection": {
                "edges": [
                    {
                        "node": {
                            "legs": [
                                {
                                    "mode": "WALK",
                                    "distance": 300,
                                    "from": {"name": "Casa"},
                                    "to": {"name": "Estação"},
                                    "route": None,
                                },
                                {
                                    "mode": "RAIL",
                                    "distance": 24100,
                                    "from": {"name": "Estação Carapicuíba"},
                                    "to": {"name": "Luz"},
                                    "route": {"shortName": "8-Diamante", "longName": "Júlio Prestes"},
                                },
                            ]
                        }
                    }
                ]
            }
        }
    }


@pytest.fixture
def otp_payload_vazio():
    return {"data": {"planConnection": {"edges": []}}}


@pytest.fixture
def osrm_ok_response():
    return {
        "code": "Ok",
        "routes": [
            {
                "distance": 24500.0,
                "geometry": {"coordinates": [[-46.8355, -23.5228], [-46.6333, -23.5505]]},
            }
        ],
    }
