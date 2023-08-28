import copy
from dataclasses import dataclass
from typing import Iterator, NewType

from sqlalchemy import Column, ForeignKey, Integer, JSON, String
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import relationship

from pbench.server.database.database import Database
from pbench.server.database.models.datasets import Dataset


class IndexMapError(Exception):
    """
    This is a base class for errors reported by the IndexMap class. It is
    never raised directly, but may be used in "except" clauses.
    """

    pass


class IndexMapSqlError(IndexMapError):
    """SQLAlchemy errors reported through IndexMap operations.

    The exception will identify the base name of the Elasticsearch index,
    along with the operation being attempted.
    """

    def __init__(self, operation: str, dataset: Dataset, name: str, cause: str):
        self.dataset = dataset.name if dataset else "unknown"
        super().__init__(f"Error {operation} index {self.dataset}:{name}: {cause}")
        self.operation = operation
        self.name = name
        self.cause = cause


class IndexMapDuplicate(IndexMapError):
    """Attempt to commit a duplicate IndexMap id."""

    def __init__(self, name: str, cause: str):
        super().__init__(f"Duplicate index map {name!r}: {cause!r}")
        self.name = name
        self.cause = cause


class IndexMapMissingParameter(IndexMapError):
    """Attempt to commit a IndexMap with missing parameters."""

    def __init__(self, name: str, cause: str):
        super().__init__(f"Missing required parameters in {name!r}: {cause}")
        self.name = name
        self.cause = cause


@dataclass
class IndexStream:
    index: str
    id: str


IndexMapType = NewType("IndexMapType", dict[str, dict[str, list[str]]])


class IndexMap(Database.Base):
    """
    A Pbench Elasticsearch index map. This records all of the versioned indices
    occupied by documents from a dataset, and the document IDs in each index.

    Columns:
        id          Generated unique ID of table row
        dataset     Reference to the associated dataset
        index       Elasticsearch full index name
        documents   JSON list of document IDs
    """

    __tablename__ = "indexmaps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_ref = Column(Integer, ForeignKey("datasets.id"), nullable=False)
    root = Column(String(255), index=True, nullable=False)
    index = Column(String(255), index=True, nullable=False)
    documents = Column(JSON, nullable=False)
    dataset = relationship("Dataset")

    @classmethod
    def create(cls, dataset: Dataset, map: IndexMapType):
        """
        A simple factory method to construct a set of new index rows from a
        JSON document.

        The source JSON document has a nested structure associating a set of
        "root index" names (such as "run-toc") with a set of fully qualified
        index names (with prefix and timeseries date suffix) such as
        "prefix.run-toc.2023-07", where each fully qualified index name has
        a list of document IDs:

        {
            "root-a": {
                "index-a.1": ["id1", "id2", ...],
                "index-a.2": ["id3", "id4", ...]
            },
            "root-b": {
                "index-b.1": ["id5", "id6", ...],
                "index-b.2": ["id7", "id8", ...]
            }
        }

        We usually iterate through all document IDs for a particular root
        index name, so we break down the JSON to store a document ID list for
        each index in a separate row.

        Args:
            dataset: the Dataset object
            map: a JSON index map
        """
        instances = []
        for root, indices in map.items():
            for index, docs in indices.items():
                m = IndexMap(dataset=dataset, root=root, index=index, documents=docs)
                instances.append(m)

        try:
            Database.db_session.add_all(instances)
        except Exception as e:
            raise IndexMapSqlError("add_all", dataset, "all", e)

        cls.commit(dataset, "create")

    @classmethod
    def merge(cls, dataset: Dataset, merge_map: IndexMapType):
        """Merge two index maps, generated by distinct phases of indexing.

        Generally the root and index names won't overlap, but we allow for that
        just in case.

        This does not de-dup document IDs: the use case for this method is to
        merge a map containing "tool-data-{name}" indices from a tool index
        pass into a previous general indexing map that will not contain
        "tool-data-{name}" indices.

        Args:
            merge_map: an index map to merge into the indexer map attribute
        """

        try:
            indices = (
                Database.db_session.query(IndexMap)
                .filter(IndexMap.dataset == dataset)
                .all()
            )

            # Cross reference the list of IndexMap entries by root and full
            # index name in a structure similar to IndexMapType. (But the
            # leaf nodes point back to the DB model objects to allow updating
            # them.) Note that we allow for a list of IndexMap model objects
            # for each fully qualified index name although in theory that
            # shouldn't happen.
            map: dict[str, dict[str, list[IndexMap]]] = {}
            for i in indices:
                if i.root in map.keys():
                    if i.index in map[i.root].keys():
                        map[i.root][i.index].append(i)
                    else:
                        map[i.root][i.index] = [i]
                else:
                    map[i.root] = {i.index: [i]}

            old_roots = set(map.keys())
            new_roots = set(merge_map.keys())

            # Any new roots can just be added to the table
            for r in new_roots - old_roots:
                for i, d in merge_map[r].items():
                    Database.db_session.add(
                        IndexMap(dataset=dataset, root=r, index=i, documents=d)
                    )

            # Roots in both need to be merged
            for r in old_roots & new_roots:
                old_indices = set(map[r].keys())
                new_indices = set(merge_map[r].keys())

                # New indices can be added to the table
                for i in new_indices - old_indices:
                    Database.db_session.add(
                        IndexMap(
                            dataset=dataset, root=r, index=i, documents=merge_map[r][i]
                        )
                    )

                # Indices in both need to merge the document ID lists
                changed = old_indices & new_indices
                for i in changed:
                    model = map[r][i][0]  # Always update the first

                    # The deep copy ensures that SQLAlchemy will notice the
                    # change and update the DB row.
                    x = copy.deepcopy(model.documents)
                    x.extend(merge_map[r][i])
                    model.documents = x
        except SQLAlchemyError as e:
            raise IndexMapSqlError("merge", dataset, "all", str(e))

        cls.commit(dataset, "merge")

    @staticmethod
    def indices(dataset: Dataset, root: str) -> Iterator[str]:
        """Return the indices matching the specified root index name.

        Args:
            dataset: Dataset object
            root: Root index name

        Raises:
            IndexMapSqlError: problem interacting with Database

        Returns:
            The index names matching the root index name
        """
        try:
            map = (
                Database.db_session.query(IndexMap)
                .filter(IndexMap.dataset == dataset, IndexMap.root == root)
                .all()
            )
        except SQLAlchemyError as e:
            raise IndexMapSqlError("finding", dataset, root, str(e))

        return (i.index for i in map)

    @staticmethod
    def exists(dataset: Dataset) -> bool:
        """Determine whether the dataset has at least one map entry.

        Args:
            dataset: Dataset object

        Returns:
            True if the dataset has at least one index map entry
        """

        try:
            c = (
                Database.db_session.query(IndexMap)
                .filter(IndexMap.dataset == dataset)
                .count()
            )
            return bool(c)
        except SQLAlchemyError as e:
            raise IndexMapSqlError("checkexist", dataset, "any", str(e))

    @staticmethod
    def stream(dataset: Dataset) -> Iterator[IndexStream]:
        """Stream the index and document ID data

        Args:
            dataset: Dataset object

        Raises:
            IndexMapSqlError: problem interacting with Database
            IndexMapNotFound: the specified template doesn't exist

        Returns:
            A stream of index info
        """
        try:
            indices: Iterator[IndexMap] = (
                Database.db_session.query(IndexMap)
                .filter(IndexMap.dataset == dataset)
                .all()
            )
        except SQLAlchemyError as e:
            raise IndexMapSqlError("streaming", dataset, "all", str(e))

        for m in indices:
            for id in m.documents:
                yield IndexStream(index=m.index, id=id)

    def __str__(self) -> str:
        """
        Return a string representation of the map object

        Returns:
            string: Representation of the template
        """
        return (
            f"{self.dataset.name} [{self.root}:{self.index}]: {len(self.documents)} IDs"
        )

    @staticmethod
    def _decode(index: str, exception: IntegrityError) -> Exception:
        """
        Decode a SQLAlchemy IntegrityError to look for a recognizable UNIQUE
        or NOT NULL constraint violation. Return the original exception if
        it doesn't match.

        Args:
            index: The index name
            exception: An IntegrityError to decode

        Returns:
            a more specific exception, or the original if decoding fails
        """
        # Postgres engine returns (code, message) but sqlite3 engine only
        # returns (message); so always take the last element.
        cause = exception.orig.args[-1]
        if "UNIQUE constraint" in cause:
            return IndexMapDuplicate(index, cause)
        elif "NOT NULL constraint" in cause:
            return IndexMapMissingParameter(index, cause)
        return exception

    @classmethod
    def commit(cls, dataset: Dataset, operation: str):
        """Commit changes to the database."""
        try:
            Database.db_session.commit()
        except IntegrityError as e:
            Database.db_session.rollback()
            raise cls._decode("any", e)
        except Exception as e:
            Database.db_session.rollback()
            raise IndexMapSqlError(operation, dataset, "any", str(e))