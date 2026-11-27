import json
import math
from pathlib import Path
import pytest
from worldcompute.sim_mapping import simulation_mapping, load_mapping
from worldcompute.so101_mapping import model_state, wc_targets


def test_mapping_routing_and_gripper_endpoints(tmp_path):
    mapping=simulation_mapping()
    assert load_mapping('sim') == mapping
    pose=dict.fromkeys(mapping['joints'], 0.)
    for rad, percent in [(-.21,0), (1.5,100)]:
        pose['gripper']=rad
        values=model_state(pose,mapping)
        assert values[-1] == pytest.approx(percent)
        assert wc_targets([values],mapping)[0] == pytest.approx(pose)
    path=tmp_path/'mapping.json'; path.write_text(json.dumps(mapping))
    with pytest.raises(ValueError,match='physical robot'):
        load_mapping('robot',path)
    path.write_text(json.dumps({'joints': {}}))
    with pytest.raises(ValueError,match='physical station'):
        load_mapping('sim',path)
    with pytest.raises(ValueError,match='Replay requires'):
        load_mapping('sim',replay=True)


def test_geometric_mapping_matches_link_vectors_and_jaw_axes():
    np=pytest.importorskip('numpy')
    k=pytest.importorskip('dreamscale.so101_kinematics')
    joints=json.loads((Path(__file__).parent/'data/playground-joints.json').read_text())
    mapping=simulation_mapping()
    # Independent fixture of the actual renderer profile; base frames differ by yaw.
    base=k._rot_z(-math.pi/2)[:3,:3]
    rng=np.random.default_rng(42)
    for _ in range(64):
        q={j['name']:float(rng.uniform(j['lower'],j['upper'])) for j in joints}
        values=model_state(q,mapping)
        T=np.eye(4); sim=[]
        for j in joints[:5]:
            T=T@k._transform(j['xyz'],j['rpy']);sim.append(T[:3,3].copy())
            a=np.array(j['axis']);x,y,z=a
            K=np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
            R=np.eye(4);angle=q[j['name']]
            R[:3,:3]=np.eye(3)+math.sin(angle)*K+(1-math.cos(angle))*(K@K)
            T=T@R
        M=np.eye(4);model=[]
        for origin,angle in zip(k._ORIGINS,values):
            M=M@origin;model.append(base@M[:3,3]);M=M@k._rot_z(math.radians(angle))
        for i in [1,2]:
            np.testing.assert_allclose(sim[i+1]-sim[i],model[i+1]-model[i],atol=5e-6)
        tool=base@(M@k._TOOL_T)[:3,:3]
        np.testing.assert_allclose(T[:3,:3]@np.array([0,-1,0]),tool[:,2],atol=5e-5)
        # SO100 jaw hinge is -Z; SO101 jaw hinge is -tool Y.
        np.testing.assert_allclose(-T[:3,2],-tool[:,1],atol=5e-5)
