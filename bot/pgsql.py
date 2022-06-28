from typing import Any

import psycopg2
from psycopg2 import sql
from loguru import logger
import os
from typing import TypedDict
from psycopg2.extensions import cursor
import psycopg2.errors


class ValidColumns(TypedDict, total=False):
    pass


class ConnectionWrapper:
    try:

        logger.debug("Trying to connect to db")
        con = psycopg2.connect(
            database=os.getenv("POSTGRES_DB"),
            user="postgres",
            password="postgres",
            host=os.getenv("PG_HOST", "db"),
            port="5432"
        )
        logger.debug(
            f"Connected to db {con.info.dbname} with user {con.info.user}"
        )

    except psycopg2.OperationalError:
        logger.critical("Unable to Connect to DB")
        raise

    except ImportError:
        logger.critical("Unable to Import psycopg2")
        raise

    def __execute_query(self, query: str | sql.Composable, commit: bool = True) -> cursor:
        cur = self.con.cursor()
        cur.execute(query)
        if commit:
            self.con.commit()
        return cur

    def ensure_base_tables(self):
        pass

    def __drop_table(self):
        try:
            self.__execute_query("""DROP TABLE bot_data""")
        except psycopg2.errors.UndefinedTable:
            logger.debug("Table Does not exits.. skipping")

    def insert(self):
        # todo:- make insert function generic
        pass

    def get(
            self,
            columns: tuple[str, ...],
            conditions: ValidColumns | None = None,
            table=None,
    ) -> cursor:
        """
        A generic get function to get values from db

        :param columns:
        :param conditions:
        :param table:
        :return: psycopg2.Cursor
        """
        format_kwargs = {
            'columns': sql.SQL(',').join([sql.Identifier(i) for i in columns])
            if columns[0] != '*' else sql.SQL("*"),

            'table': sql.Identifier(table),
        }
        if conditions:
            format_kwargs.update(
                {
                    'conditions': sql.SQL(',').join(
                        [
                            sql.SQL('=').join((sql.Identifier(key), sql.Literal(value)))
                            for key, value in conditions.items()
                        ]
                    )
                }
            )
        query = sql.SQL(
            "SELECT {columns} FROM {table} " +
            ("where {conditions}" if conditions else '')
        ).format(**format_kwargs)

        return self.__execute_query(query, commit=False)

    def update(self, table: str, where: tuple[str, Any], returning: str | None = None, **kwargs) -> cursor:
        update_fields = []
        for column, value in kwargs.items():
            update_fields.append(sql.SQL("=").join(
                [sql.Identifier(str(column)), sql.Literal(value)]
            ))

        format_kwargs = {
            'table': sql.Identifier(table),
            'update_fields': sql.SQL(',').join(update_fields),
            'condition': sql.SQL('=').join([sql.Identifier(where[0]), sql.Literal(where[1])]),
        }
        if returning:
            format_kwargs.update({'returning': sql.Identifier(returning)})

        query = sql.SQL(
            """UPDATE {table} SET {update_fields} where {condition} """
            + ("RETURNING (SELECT {returning} FROM {table} WHERE {condition})" if returning else '')
        ).format(**format_kwargs)

        return self.__execute_query(query)

    def exists(self, where: tuple[str, Any], table: str = 'bot_data') -> bool:
        # SELECT exists (SELECT 1 FROM table WHERE column = <value> LIMIT 1);
        query = sql.SQL(
            "SELECT exists (SELECT 1 FROM {table} WHERE {condition} LIMIT 1)"
        ).format(
            table=sql.Identifier(table),
            condition=sql.SQL('=').join([
                sql.Identifier(where[0]),
                sql.Literal(where[1])
            ])
        )
        with self.__execute_query(query, commit=False) as curr:
            return curr.fetchone()[0]

    def delete(self, table: str, conditions: ValidColumns) -> cursor:
        # DELETE
        # from vc_data
        # WHERE channel_id={channel_id}

        query = sql.SQL("DELETE from {table} where {conditions}").format(
            table=sql.Identifier(table),
            conditions=sql.SQL(',').join(
                [
                    sql.SQL('=').join((sql.Identifier(key), sql.Literal(value)))
                    for key, value in conditions.items()
                ])
        )
        return self.__execute_query(query)
