import sys
from db_init import init_sql_server 
from agent_sql import agent

steps = {"init-sql": "step_init_sql", "agent-sql": "step_agent_sql" }



def step_init_sql():
    init_sql_server()


def step_agent_sql():
    agent()





def run(argv):
    if len(argv) == 1:
         steps["agent-sql"]
        
    if argv[1] == "init-sql":
        steps["init-sql"]()



                



if __name__ == "__main__":
    run(sys.argv)
