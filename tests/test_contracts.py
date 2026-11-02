import unittest
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import networkx as nx
from scipy.sparse import csr_matrix

from territory_planner.data import read_assignment, read_config
from territory_planner.evaluation import evaluate


class ContractTests(unittest.TestCase):
    def test_duplicate_assignment_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'bad.csv'
            pd.DataFrame({'unit_id':[0,0],'territory_id':[1,2]}).to_csv(p,index=False)
            with self.assertRaisesRegex(ValueError,'完整且唯一'):read_assignment(p,2,2)

    def test_fractional_and_missing_groups_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'bad.csv'
            for labels in [[1,1.5],[1,1]]:
                pd.DataFrame({'unit_id':[0,1],'territory_id':labels}).to_csv(p,index=False)
                with self.assertRaises(ValueError):read_assignment(p,2,2)

    def test_valid_assignment_is_ordered_by_id(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'valid.csv'
            pd.DataFrame({'unit_id':[1,0],'territory_id':[2,1]}).to_csv(p,index=False)
            self.assertTrue(np.array_equal(read_assignment(p,2,2),[0,1]))

    def fixture(self):
        roads=np.array([[0,1,0,0],[1,0,1,0],[0,1,0,1],[0,0,1,0]],dtype=float)
        graph=nx.complete_graph(4)
        data={'attrs':np.ones((4,3)), 'graph':graph,'roads':csr_matrix(roads),
              'info':{'street':np.arange(4),'rep_indices':np.arange(4)}}
        config={'hc':2,'tolerance':[0,0,0],'distance_cap_km':1}
        return data,config

    def test_valid_directed_road_partition(self):
        data,config=self.fixture()
        result=evaluate(data,config,np.array([0,0,1,1]))
        self.assertTrue(result['accepted'])
        self.assertEqual(result['maximum_span_km'],1)

    def test_routes_cannot_borrow_another_territory(self):
        data,config=self.fixture()
        result=evaluate(data,config,np.array([0,1,0,1]))
        self.assertTrue(result['street_connectivity_pass'])
        self.assertFalse(result['road_connectivity_pass'])
        self.assertFalse(result['accepted'])

    def test_one_way_reachability_is_insufficient(self):
        data,config=self.fixture()
        data['roads'][1,0]=0
        data['roads'].eliminate_zeros()
        self.assertFalse(evaluate(data,config,np.array([0,0,1,1]))['accepted'])


if __name__=='__main__':unittest.main()
