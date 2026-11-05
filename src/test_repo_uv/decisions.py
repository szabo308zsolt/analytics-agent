from openai import OpenAI

client = OpenAI()


def analytics_decision(question) -> bool:
    decision = client.decisions.create(
        model="gpt-6-luna",
        input=question,
        questions=[
            {
                "type": "choice",
                "instructions": "Return True if the input is a genuine request of analytical knowledge assuming the underlying data is available for it. Otherwise return False.",
                "choices": [
                    {
                        "value": "True"
                    },
                    {
                        "value": "False"
                    }
                ]
            }
        ],
    )
    return True if decision.answers[0].choice == 'True' else False


if __name__ == "__main__":
    question = "what is the median household income of singapore"
    print(analytics_decision(question))