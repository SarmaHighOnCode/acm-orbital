import time
import numpy as np
from scipy.integrate import solve_ivp
from engine.propagator import OrbitalPropagator
from config import MU_EARTH, J2, R_EARTH

def vectorized_derivatives(t, state_flat, n_objects):
    # state_flat is shape (6 * N,)
    state = state_flat.reshape(n_objects, 6)
    pos = state[:, :3] # shape (N, 3)
    vel = state[:, 3:] # shape (N, 3)
    
    x = pos[:, 0]
    y = pos[:, 1]
    z = pos[:, 2]
    
    r = np.linalg.norm(pos, axis=1) # shape (N,)
    
    # 2-body
    a_gravity = -MU_EARTH * pos / (r[:, np.newaxis]**3)
    
    # J2
    factor = 1.5 * J2 * MU_EARTH * R_EARTH**2 / (r**5)
    z2_r2 = (z / r)**2
    
    a_j2_x = factor * x * (5.0 * z2_r2 - 1.0)
    a_j2_y = factor * y * (5.0 * z2_r2 - 1.0)
    a_j2_z = factor * z * (5.0 * z2_r2 - 3.0)
    
    a_j2 = np.column_stack([a_j2_x, a_j2_y, a_j2_z])
    
    acc = a_gravity + a_j2
    
    return np.concatenate([vel.flatten(), acc.flatten()])

def run_benchmark():
    N = 10000
    np.random.seed(42)
    # create N random valid LEO states
    positions = np.random.uniform(-7000, 7000, size=(N, 3))
    # normalize and scale to 7000km
    norm = np.linalg.norm(positions, axis=1, keepdims=True)
    positions = positions / norm * 7000.0
    
    velocities = np.random.uniform(-7, 7, size=(N, 3))
    
    states = np.column_stack([positions, velocities])
    
    prop = OrbitalPropagator(rtol=1e-6, atol=1e-8) # slightly lower tolerance for speed
    
    # Method 1: Vectorized ODE
    start = time.time()
    state_flat = states.flatten()
    
    sol = solve_ivp(
        vectorized_derivatives,
        [0.0, 60.0],
        state_flat,
        args=(N,),
        method="DOP853",
        rtol=1e-6,
        atol=1e-8,
        dense_output=False,
    )
    res_flat = sol.y[:, -1]
    vector_res = res_flat.reshape(N, 6)
    vec_time = time.time() - start
    print(f"Vectorized Time for {N}: {vec_time:.4f}s")
    
if __name__ == "__main__":
    run_benchmark()
