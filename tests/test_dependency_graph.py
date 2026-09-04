"""F35 依赖图 mermaid 导出（spec §3.2）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestToMermaid:
    def _graph(self):
        from module_designer.dependency_graph import (
            DependencyEdge, DependencyGraph, DependencyNode)
        g = DependencyGraph()
        g.nodes["I1"] = DependencyNode(entity_id="I1", entity_type="interaction",
                                       name="搜索墙壁")
        g.nodes["AT2"] = DependencyNode(entity_id="AT2", entity_type="auto_trigger",
                                        name="尸体异变")
        g.nodes["END_TEST"] = DependencyNode(entity_id="END_TEST",
                                             entity_type="ending", name="测试结局")
        g.edges.append(DependencyEdge(source="AT2", target="I1",
                                      dep_type="interaction"))
        g.edges.append(DependencyEdge(source="END_TEST", target="AT2",
                                      dep_type="auto_trigger"))
        return g

    def test_nodes_and_edges_rendered(self):
        m = self._graph().to_mermaid()
        assert m.startswith("flowchart TD")
        assert "I1" in m and "搜索墙壁" in m
        assert "AT2" in m and "尸体异变" in m
        assert "AT2 --> I1" in m

    def test_ending_highlighted(self):
        m = self._graph().to_mermaid()
        assert "END_TEST" in m
        assert "classDef" in m

    def test_circular_marked(self):
        from module_designer.dependency_graph import (
            DependencyEdge, DependencyGraph, DependencyNode)
        g = DependencyGraph()
        g.nodes["A"] = DependencyNode(entity_id="A")
        g.nodes["B"] = DependencyNode(entity_id="B")
        g.edges.append(DependencyEdge(source="A", target="B"))
        g.edges.append(DependencyEdge(source="B", target="A"))
        m = g.to_mermaid()
        assert "环" in m
